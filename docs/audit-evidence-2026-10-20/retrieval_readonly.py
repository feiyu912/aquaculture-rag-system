"""Small real local-model retrieval probe, no LLM or persistent writes.
Run from apps/api with HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1.
"""
import asyncio,json,sys,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'apps/api'))
from sqlalchemy import text
from app.db import SessionLocal,engine
from app.config import settings
from app.ingestion.embedder import get_embedder
from app.retrieval.rerank import build_reranker
from app.retrieval.bm25 import BM25SparseEncoder
from app.retrieval.service import retrieve
async def main():
 cases={c['id']:c for c in map(json.loads,(ROOT/'eval/real_questions_v1.jsonl').read_text().splitlines())}
 e=get_embedder(settings.embedding_model,settings.qdrant_vector_size,settings.embedding_device,settings.embedding_use_fp16,settings.embedding_batch_size,settings.embedding_max_length)
 v=await asyncio.to_thread(e.embed_query,'水产养殖溶解氧指标')
 r=build_reranker(settings.reranker_model,path=settings.reranker_path,device=settings.reranker_device,use_fp16=settings.reranker_use_fp16)
 out={'model':{'embedder':e.name,'device':e.device,'dim':len(v),'norm':math.sqrt(sum(x*x for x in v))},'reranker_pair':r.rerank('水体溶解氧有什么要求？',[('irrelevant','今天上海天气晴朗。'),('relevant','养殖水体溶解氧保持5 mg/L以上。')],2),'cases':[]}
 for key in ['R061','R062','R064','R066','UNDATED']:
  c=cases[key] if key!='UNDATED' else {'question':'水产养殖禁用渔药完整清单有哪些？'}
  async with SessionLocal() as db:
   await db.execute(text('SET TRANSACTION READ ONLY'))
   result=await retrieve(db,c['question'],e,BM25SparseEncoder(),reranker=r,mode='hybrid_rerank',species=c.get('species'),category=c.get('category'))
   out['cases'].append({'id':key,'question':c['question'],'sufficient':result.sufficient,'gate':result.gate,'timings':result.timings,'source_aware':result.config.get('source_aware_retrieval'),'targeted':result.config.get('targeted_retrieval'),'evidence':[{'parent':str(x.parent_chunk_id),'child':str(x.child_chunk_id),'title':x.title,'page':x.page,'quote':x.quote} for x in result.evidence]})
   await db.rollback()
  print(key,result.sufficient,result.gate['reason'],[str(x.parent_chunk_id) for x in result.evidence],result.timings,flush=True)
 await engine.dispose()
 (Path(__file__).parent/'retrieval-readonly.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
 print(out['model'],out['reranker_pair'])
asyncio.run(main())

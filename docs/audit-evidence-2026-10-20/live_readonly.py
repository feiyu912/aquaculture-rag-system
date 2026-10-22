"""Read-only PG/Qdrant snapshot; never prints credentials or conversations.
Run from apps/api: .venv/bin/python ../../docs/audit-evidence-2026-10-20/live_readonly.py
"""
import asyncio,json,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'apps/api'))
from sqlalchemy import text,select,func
from app.db import SessionLocal,engine
from app.config import settings
from app.models import KbDocument,KbDocumentVersion,KbChunk,GraphRelation,IndexManifest
from app.retrieval.vector_store import get_client,count_version_points

async def main():
 out={}
 async with SessionLocal() as db:
  await db.execute(text('SET TRANSACTION READ ONLY'))
  for label,model in [('documents',KbDocument),('versions',KbDocumentVersion)]:
   rows=(await db.execute(select(model.status,func.count()).group_by(model.status))).all()
   out[label]=dict(rows)
  docs=(await db.execute(select(KbDocument).where(KbDocument.status=='active',KbDocument.current_version_id.is_not(None)))).scalars().all()
  out['active']=[]
  client=get_client()
  try:
   for d in docs:
    v=await db.get(KbDocumentVersion,d.current_version_id)
    counts=dict((await db.execute(select(KbChunk.chunk_role,func.count()).where(KbChunk.document_version_id==v.id).group_by(KbChunk.chunk_role))).all())
    out['active'].append({'document_id':str(d.id),'version_id':str(v.id),'title':d.title,'status':v.status,'version':v.version_no,'embedding_model':v.embedding_model,'chunk_config_hash':v.chunk_config_hash,'db_chunks':counts,'qdrant_points':count_version_points(client,v.id)})
   out['collections']=[]
   for c in client.get_collections().collections:
    info=client.get_collection(c.name)
    out['collections'].append({'name':c.name,'points':info.points_count,'vectors':str(info.config.params.vectors),'sparse':str(info.config.params.sparse_vectors)})
  finally: client.close()
  relations=(await db.execute(select(GraphRelation))).scalars().all()
  out['graph']={'relations':len(relations),'verified':sum(r.review_status=='verified' for r in relations),'verified_without_provenance':sum(r.review_status=='verified' and r.provenance_document_version_id is None for r in relations)}
  manifests=(await db.execute(select(IndexManifest))).scalars().all()
  out['manifests']=[{'collection':m.collection,'status':m.status,'embedding_model':m.embedding_model,'point_count':m.point_count,'document_count':m.document_count,'chunk_hash':m.chunk_config_hash,'bm25_hash':m.bm25_config_hash} for m in manifests]
  cases=[json.loads(l) for l in (ROOT/'eval/real_questions_v1.jsonl').read_text().splitlines()]
  out['gold_version_active']=all(any(str(d.current_version_id)==g['version_id'] for d in docs) for c in cases for g in c['gold'])
  out['special_gold_chunks']={}
  for c in cases:
   if c['id'] not in ['R061','R062','R064','R066']:continue
   out['special_gold_chunks'][c['id']]=[]
   for g in c['gold']:
    chunk=await db.get(KbChunk,uuid.UUID(g.get('parent_chunk_id') or g['chunk_id']))
    out['special_gold_chunks'][c['id']].append({'parent_id':str(chunk.id),'content':chunk.content,'heading':chunk.heading_path,'page_from':chunk.page_from,'page_to':chunk.page_to,'locations':chunk.locations})
  await db.rollback()
 await engine.dispose()
 p=Path(__file__).parent/'live-readonly.json';p.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({k:v for k,v in out.items() if k!='special_gold_chunks'},ensure_ascii=False,indent=2))
asyncio.run(main())

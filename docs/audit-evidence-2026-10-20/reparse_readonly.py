"""Compare current parser/chunker output with stored real-standard chunks, no writes."""
import asyncio,json,sys,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'apps/api'))
from sqlalchemy import select,text
from app.db import SessionLocal,engine
from app.models import KbDocument,KbDocumentVersion,KbChunk
from app.ingestion.parser import PyMuPDFParser
from app.ingestion.chunker import build_chunks
from app.ingestion.pipeline import chunk_config_hash
from app.config import settings
async def main():
 out=[]
 async with SessionLocal() as db:
  await db.execute(text('SET TRANSACTION READ ONLY'))
  rows=(await db.execute(select(KbDocument,KbDocumentVersion).join(KbDocumentVersion,KbDocument.current_version_id==KbDocumentVersion.id).where(KbDocument.status=='active'))).all()
  for d,v in rows:
   if not d.title.startswith(('DB32','DB36','DB46')):continue
   path=Path(v.file_path);parsed=PyMuPDFParser().parse(path)
   fresh=build_chunks(parsed,v.id,parent_target=settings.parent_target_chars,child_target=settings.child_target_chars,overlap=settings.child_overlap_chars)
   old=(await db.execute(select(KbChunk).where(KbChunk.document_version_id==v.id))).scalars().all()
   oldids={c.id for c in old};newids={c.id for c in fresh}
   out.append({'title':d.title,'file_hash_matches':hashlib.sha256(path.read_bytes()).hexdigest()==v.content_hash,'stored_parser_version':v.parser_version,'runtime_parser_version':parsed.parser_version,'stored_chunk_hash':v.chunk_config_hash,'runtime_chunk_hash':chunk_config_hash(),'stored_parents':sum(c.chunk_role=='parent' for c in old),'stored_children':sum(c.chunk_role=='child' for c in old),'fresh_parents':sum(c.role=='parent' for c in fresh),'fresh_children':sum(c.role=='child' for c in fresh),'shared_ids':len(oldids&newids),'stored_total':len(oldids),'fresh_total':len(newids),'fresh_env_parents':[{'text':c.content,'heading':c.heading_path,'id':str(c.id)} for c in fresh if c.role=='parent' and '溶解氧含量保持' in c.content]})
  await db.rollback()
 await engine.dispose();(Path(__file__).parent/'reparse-readonly.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps(out,ensure_ascii=False,indent=2))
asyncio.run(main())

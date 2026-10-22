"""Read-only independent rescoring. Run from repository root with Python 3."""
import hashlib
import json
import math
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent

def score(ranked, gold):
    relevant = {c: g for c, g in gold.items() if g > 0}
    ideal = sorted(relevant.values(), reverse=True)
    def dcg(grades):
        return sum((2**g-1)/math.log2(i+2) for i,g in enumerate(grades))
    result = {}
    for k in (5,10):
        result[f'recall@{k}'] = len(set(ranked[:k]) & set(relevant))/len(relevant) if relevant else 0
        denom=dcg(ideal[:k])
        result[f'ndcg@{k}'] = dcg([relevant.get(c,0) for c in ranked[:k]])/denom if denom else 0
    first=next((i for i,c in enumerate(ranked[:10],1) if c in relevant),None)
    result['mrr@10']=1/first if first else 0
    return result

def mean(rows):
    return {k:round(statistics.mean(r[k] for r in rows),6) for k in rows[0]} if rows else {}

cases=[json.loads(l) for l in (ROOT/'eval/real_questions_v1.jsonl').read_text().splitlines() if l.strip()]
output={'dataset_sha256':hashlib.sha256((ROOT/'eval/real_questions_v1.jsonl').read_bytes()).hexdigest(),
        'cases':len(cases),'expected_answerable':sum(not c['expect_insufficient'] for c in cases),
        'gold_document_titles':sorted({g['title'] for c in cases for g in c['gold']}),
        'counterexample':score(['wrong','correct'],{'correct':2})}
output['runs']={}
for name in ['real_questions_v1_1_query_ir','real_questions_v1_1_no_query_ir','real_questions_v1_1_ctx_query_ir','real_questions_v1_1_ctx_no_query_ir','real_questions_v1_source_aware','r061_source_aware']:
    p=ROOT/'eval/runs'/name/'details.jsonl'
    rows=[json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    output['runs'][name]={}
    for mode in sorted({r['mode'] for r in rows}):
        selected=[r for r in rows if r['mode']==mode and not r['expect_insufficient'] and 'gold' in r]
        output['runs'][name][mode]={'n':len(selected),'recomputed':mean([score(r['ranked_chunk_ids'],r['gold']) for r in selected]),
          'old_ndcg10':round(statistics.mean(r['ndcg@10'] for r in selected),6) if selected else None,
          'expected_refusal':[{ 'id':r['id'],'refused':r['refused'],'reason':r['reason']} for r in rows if r['mode']==mode and r['expect_insufficient']],
          'special_cases':{r['id']:{'ranked':r.get('ranked_chunk_ids'),'gold':r.get('gold'),'corrected':score(r.get('ranked_chunk_ids',[]),r.get('gold',{})),'reason':r['reason']} for r in rows if r['mode']==mode and r['id'] in ['R061','R062','R064','R066']}}
    output['runs'][name]['input_sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
ab=json.loads((ROOT/'eval/runs/planner_retrieval_ab_70_v5.json').read_text())
output['planner']={}
for family in ('rules','llm'):
    rows=ab['details']
    ans=[r for r in rows if r[family]['sufficient']]
    expected=[r for r in rows if not next(c for c in cases if c['id']==r['id'])['expect_insufficient']]
    output['planner'][family]={
      'all70':mean([score(r[family]['ranked_parent_ids'],r['gold']) for r in rows]),
      'expected_answerable67':mean([score(r[family]['ranked_parent_ids'],r['gold']) for r in expected]),
      'actually_answered65':mean([score(r[family]['ranked_parent_ids'],r['gold']) for r in ans]),
      'refused':[r['id'] for r in rows if not r[family]['sufficient']]}
output['planner']['deltas']=[{'id':r['id'],'rules':score(r['rules']['ranked_parent_ids'],r['gold']),'llm':score(r['llm']['ranked_parent_ids'],r['gold'])} for r in ab['details'] if score(r['rules']['ranked_parent_ids'],r['gold'])!=score(r['llm']['ranked_parent_ids'],r['gold'])]
output['planner']['errors']=[{'id':r['id'],'error':r['llm']['planner']['error']} for r in ab['details'] if (r['llm'].get('planner') or {}).get('error')]
output['planner']['used']=sum(bool((r['llm'].get('planner') or {}).get('used_llm')) for r in ab['details'])
quality=[json.loads(l) for l in (ROOT/'eval/runs/answer_quality_v1/details.jsonl').read_text().splitlines() if l.strip()]
output['answer_quality']={f:{'n':len(quality),'answered':sum(r[f]['answered'] for r in quality),'citation_coverage_mean':round(statistics.mean(r[f]['citation_coverage'] for r in quality),6),'invalid_citation_cases':sum(bool(r[f]['invalid_citations']) for r in quality),'gold_source_cited':sum(r[f]['gold_source_cited'] for r in quality)} for f in ('rules','llm')}
(OUT/'recomputed.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in output.items() if k!='runs'},ensure_ascii=False,indent=2))
for name,run in output['runs'].items():
    print(name, {k:v['recomputed'] for k,v in run.items() if isinstance(v,dict) and 'recomputed' in v})

import json
kpis = json.load(open('app/db/seeds/ontology_kpis.json', encoding='utf-8'))
lines = open('app/db/seeds/ontology_kpis.json', encoding='utf-8').read().split('\n')
res = []
for k in kpis[516:546]:
    idx = next(i for i, l in enumerate(lines) if f'"kpi_id": "{k.get("kpi_id")}"' in l)
    start = idx + 6
    end = start + 10 # skip valid_dimensions
    while '"representative_lineage": [' not in lines[end-1]:
        end += 1
    end += 1
    target = '\n'.join(lines[start-1:end])
    res.append({'start': start, 'end': end, 'target': target})
with open('temp_targets.json', 'w', encoding='utf-8') as f:
    json.dump(res, f, indent=2)

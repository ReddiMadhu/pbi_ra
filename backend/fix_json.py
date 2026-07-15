import re
text = open('app/db/seeds/ontology_kpis.json', encoding='utf-8').read()
fixed = re.sub(r'\"representative_lineage\": \[\n(.*?)\n    \],\n      \".*?\"\n    \],', r'"representative_lineage": [\n\1\n    ],', text, flags=re.DOTALL)
open('app/db/seeds/ontology_kpis.json', 'w', encoding='utf-8').write(fixed)
print("Done")

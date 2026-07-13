import sqlite3
conn = sqlite3.connect('tableau_gov.db')
c = conn.cursor()
c.execute('SELECT ai_summary FROM dashboards WHERE name = 'Dashboard 1'')
print(c.fetchall()[0][0][:200])

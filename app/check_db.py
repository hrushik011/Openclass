import sqlite3

# Make sure the path matches where your database file is located
conn = sqlite3.connect('data/classroomflow.db') 
cursor = conn.cursor()

cursor.execute("SELECT start_time, subject, batch FROM class_sessions WHERE start_time >= '13:00'")
results = cursor.fetchall()

print("Afternoon Sessions Found:")
for row in results:
    print(row)

conn.close()    
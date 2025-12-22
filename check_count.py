import mysql.connector

def delete_all_players():
    conn = mysql.connector.connect(
        host="localhost",
        user="root",
        port=3308,
        password="TARAZOU",
        database="justice_game"
    )

    cursor = conn.cursor()

    # Delete all rows from the table
    cursor.execute("DELETE FROM players;")
    conn.commit()

    print("✅ All players deleted successfully.")

    cursor.close()
    conn.close()

delete_all_players()

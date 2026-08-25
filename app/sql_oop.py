"""Подключение к SQL Server через pyodbc.

УСТАРЕЛО. Ноутбук подключается через functions/db.py: там и ClickHouse,
и SQL Server за одним интерфейсом, а база выбирается настройкой DB_ENGINE.
Класс оставлен, чтобы не сломать сторонние скрипты; для нового кода —
functions.db.create_database().

Имя MySQL историческое: подключение всегда шло к Microsoft SQL Server.
"""

import pyodbc

class MySQL:

    def __init__(self, host, user, password, db_name):
        self.connectionString = (
            f'DRIVER={{ODBC Driver 17 for SQL Server}};'
            f'SERVER={host};'
            f'DATABASE={db_name};'
            f'UID={user};'
            f'PWD={password};')
        
        try:
            self.conn = pyodbc.connect(self.connectionString)
            print('✅ Успешное подключение к БД')
        except Exception as e:
            print(f"❌ Ошибка подключения к БД: {e}")
            raise
    
    def query(self, sql, params=None):
        """Выполняет SQL-запрос и возвращает курсор с результатом"""
        cursor = self.conn.cursor()
        try:
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)
            return cursor
        except Exception as e:
            print(f"❌ Ошибка выполнения запроса: {e}")
            cursor.close()
            raise

        
    def fetch_all(self, sql: str, params=None):
        """Выполняет SELECT-запрос и возвращает все строки результата"""
        cursor = self.query(sql, params)
        try:
            rows = cursor.fetchall()
            columns =  [column[0] for column in cursor.description]
            print('✅ Данные успешно получены')
            return [dict(zip(columns, row)) for row in rows] 
        finally:
            cursor.close()
        
        
    def __del__(self):
        try:
            self.conn.close()
            print('✅ Отключились от БД')
        except:
            pass





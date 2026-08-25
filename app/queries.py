"""
Запросы под ту базу, к которой реально подключились.

DB_ENGINE переключает подключение — но не текст запроса. Это разные вещи, и
на этом легко обжечься: у баз разные схемы (media_tv_costs со справочниками
через LEFT JOIN против media_costs_union, где всё внутри) и разные диалекты
(LOWER против lowerUTF8, UNION против UNION ALL). Один и тот же SQL в обеих
базах не выполнится.

Поэтому наборов запросов два:

    clickhouse -> app/sql_dict_connection.py
    mssql      -> app/sql_dict_connection_mssql.py

КАК ПОЛЬЗОВАТЬСЯ — от подключения, а не от переменной окружения:

    db = create_database()
    Q = queries_for(db.engine)

    tv_adex = db.fetch_df(Q.TV_SQL)

Почему именно так. Раньше набор выбирался при импорте модуля, по DB_ENGINE.
В ноутбуке это давало неприятную ловушку: правишь .env, перезапускаешь
ячейки — а модуль уже лежит в sys.modules с прежним выбором, и в SQL Server
уезжает запрос для ClickHouse. Ошибка при этом приходит от драйвера и про
причину не говорит:

    ProgrammingError: [ODBC Driver 17 for SQL Server]
    lowerUTF8 не является известным имя встроенной функции.

queries_for(db.engine) берёт набор у того объекта подключения, который
сейчас в руках, так что разъехаться они не могут в принципе.

Имена TV_SQL и прочие на уровне модуля тоже остались — для скриптов, где
подключения нет (линтер, проверка на chdb). Они читают DB_ENGINE при
обращении, а не при импорте, так что тоже не устаревают.
"""

import os

from functions.db import load_env_file

#: Названия движков, означающие старую базу.
MSSQL_ALIASES = ("mssql", "sqlserver", "mysql")

#: Где лежат наборы запросов. Единственное, что нужно поправить при переносе
#: файла в другой проект, — и то лишь если там другие имена модулей.
CLICKHOUSE_QUERIES = "app.sql_dict_connection"
MSSQL_QUERIES = "app.sql_dict_connection_mssql"

def query_names(module):
    """
    Какие константы модуля считать запросами.

    Имена не перечислены списком намеренно: в соседних проектах они другие,
    и захардкоженный список пришлось бы править при каждом переносе.
    Правило то же, что у линтера (functions/sql_compat.collect_queries):
    имя прописными, значение — строка со словом SELECT. Имена с
    подчёркиванием в начале пропускаются: это заготовки шаблонов.
    """
    names = []
    for name in dir(module):
        if name.startswith("_") or not name.isupper():
            continue
        value = getattr(module, name)
        if isinstance(value, str) and "select" in value.lower():
            names.append(name)
    return names


class QuerySet:
    """Набор запросов одной базы плюс то, что о нём нужно знать."""

    def __init__(self, module, engine, source, needs_link_dict):
        self.engine = engine
        self.source = source
        self.needs_link_dict = needs_link_dict
        self.names = query_names(module)
        for name in self.names:
            setattr(self, name, getattr(module, name))

    def __repr__(self):
        return (f"<QuerySet {self.engine}: {self.source}, "
                f"запросов {len(self.names)}>")


def queries_for(engine):
    """
    Набор запросов под конкретный движок.

    engine — то, что отдаёт db.engine у объекта подключения
    ('clickhouse' или 'mssql').
    """
    engine = (engine or "clickhouse").strip().lower()

    import importlib

    if engine in MSSQL_ALIASES:
        name = MSSQL_QUERIES
        return QuerySet(importlib.import_module(name), "mssql",
                        name.replace(".", "/") + ".py", needs_link_dict=True)

    name = CLICKHOUSE_QUERIES
    return QuerySet(importlib.import_module(name), "clickhouse",
                    name.replace(".", "/") + ".py", needs_link_dict=False)


def current_engine():
    """Движок из .env — на случай, когда подключения ещё нет."""
    load_env_file()
    return (os.getenv("DB_ENGINE") or "clickhouse").strip().lower()


def __getattr__(name):
    """
    TV_SQL и прочие — для кода без подключения (скрипты, линтер).

    Через __getattr__, а не обычными присваиваниями: так значение
    вычисляется в момент обращения и не застревает с прошлого импорта.
    """
    if name.isupper() and not name.startswith("_"):
        active = queries_for(current_engine())
        if name in active.names:
            return getattr(active, name)
    if name == "ENGINE":
        return current_engine()
    if name == "SOURCE":
        return queries_for(current_engine()).source
    if name == "NEEDS_LINK_DICT":
        return queries_for(current_engine()).needs_link_dict
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["queries_for", "query_names", "current_engine", "QuerySet",
           "ENGINE", "SOURCE", "NEEDS_LINK_DICT"]

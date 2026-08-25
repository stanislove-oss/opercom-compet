"""
Доступ к базе: ClickHouse и MS SQL Server за одним интерфейсом.

Модуль намеренно самодостаточный — ничего из functions.* не импортирует.
Его можно просто скопировать в два других проекта автоматизации.

Зачем слой: переключаться между базами настройкой, а не правкой кода.

        db = create_database()              # куда идти — решает DB_ENGINE
        Q = queries_for(db.engine)          # чем спрашивать — решает подключение
        tv = db.fetch_df(Q.TV_SQL)

ВАЖНО: слой переключает только подключение. Текст запроса он не меняет и
не может: схемы и диалекты у баз разные, один и тот же SQL в обеих не
выполнится. Поэтому наборов запросов два, и берутся они у подключения —
см. app/queries.py. Если наборы всё же разъедутся, запрос не уйдёт в базу:
_check_dialect поймает это раньше и скажет, что перепутано.

Что нужно в .env:

    DB_ENGINE=clickhouse

    CLICKHOUSE_HOST=ch.example.ru
    CLICKHOUSE_PORT=8443          # 8443 — HTTPS, 8123 — HTTP
    CLICKHOUSE_USER=reporting
    CLICKHOUSE_PASSWORD=...
    CLICKHOUSE_DATABASE=media
    CLICKHOUSE_SECURE=true        # true для 8443

Клиент: clickhouse-connect (официальная библиотека, работает по HTTP).

    pip install clickhouse-connect
"""

import os
import time
from pathlib import Path

import pandas as pd

DEFAULT_HTTP_PORT = 8123
DEFAULT_HTTPS_PORT = 8443

#: Служебные базы ClickHouse. Они есть всегда и к данным отношения не имеют,
#: поэтому в списке «что вообще доступно» только мешают.
SYSTEM_DATABASES = ("system", "INFORMATION_SCHEMA", "information_schema")

#: Базы, к которым можно подключиться, когда настоящее имя ещё неизвестно.
#: Подключаться к какой-то базе обязательно — но чтобы посмотреть system.*,
#: подойдёт любая, к которой есть доступ.
DISCOVERY_DATABASES = ("default", "system")

#: Настройки запроса по умолчанию. Отчётные выгрузки большие и небыстрые,
#: поэтому лимит времени поднят, а ответ отдаётся блоками.
DEFAULT_CLICKHOUSE_SETTINGS = {
    "max_execution_time": 1800,

    # Внешние JOIN'ы ведут себя как в SQL Server: там, где совпадения нет,
    # приходит NULL, а не 0 и не пустая строка. Без этой настройки
    # «WHERE b.col IS NULL» молча перестаёт срабатывать, а нули попадают
    # в суммы и средние. Проверено запросом, см. scripts/db_test.py.
    "join_use_nulls": 1,
}


class DatabaseError(RuntimeError):
    """Ошибка подключения или запроса — с понятным текстом, а не трейсбеком драйвера."""


#: Приметы, по которым видно, для какой базы написан запрос. Нужны, чтобы
#: поймать самую обидную ошибку переезда: подключение к одной базе, а запрос
#: для другой. Драйвер в этом случае ругается на конкретную функцию, и по его
#: сообщению непонятно, что перепутаны наборы запросов целиком.
CLICKHOUSE_MARKERS = ("lowerUTF8(", "upperUTF8(", "substringUTF8(", "positionCaseInsensitive(")
MSSQL_MARKERS = ("SELECT TOP ", "ISNULL(", "GETDATE()", "CHARINDEX(")


def _check_dialect(query, engine):
    """Понятная ошибка вместо сообщения драйвера про неизвестную функцию."""
    text = str(query)

    if engine == "mssql":
        found = [m for m in CLICKHOUSE_MARKERS if m in text]
        other = "ClickHouse"
    else:
        found = [m for m in MSSQL_MARKERS if m.lower() in text.lower()]
        other = "SQL Server"

    if not found:
        return

    raise DatabaseError(
        f"Запрос написан для {other} ({', '.join(found)}), а подключение — "
        f"к {'SQL Server' if engine == 'mssql' else 'ClickHouse'}.\n"
        f"  Наборы запросов разные, брать их надо у подключения:\n"
        f"      from app.queries import queries_for\n"
        f"      Q = queries_for(db.engine)\n"
        f"      db.fetch_df(Q.TV_SQL)\n"
        f"  Если так и написано — перезапусти ядро Jupyter: модуль с прежним\n"
        f"  выбором остаётся в памяти, и правка .env на него не действует."
    )


# ---------------------------------------------------------------------------
# ClickHouse
# ---------------------------------------------------------------------------

class ClickHouseDatabase:
    """
    Подключение к ClickHouse по HTTP(S).

    Интерфейс совпадает с прежним классом app.sql_oop.MySQL, поэтому вызовы вида
    pd.DataFrame(db.fetch_all(SQL)) продолжают работать. Для новых мест
    лучше fetch_df: ClickHouse отдаёт типы колонок, и DataFrame получается
    сразу правильный, без промежуточного списка словарей.
    """

    engine = "clickhouse"

    def __init__(
        self,
        host,
        user,
        password="",
        database="default",
        port=None,
        secure=None,
        settings=None,
        connect_timeout=15,
        query_timeout=1800,
        client=None,
        verify=True,
    ):
        self.host = host
        self.user = user
        self.password = password
        self.database = database
        self.verify = verify
        self.connect_timeout = connect_timeout
        self.query_timeout = query_timeout

        # secure по умолчанию выводим из порта: 8443 — это HTTPS.
        if secure is None:
            secure = (port is None) or (int(port) == DEFAULT_HTTPS_PORT)
        self.secure = bool(secure)

        if port is None:
            port = DEFAULT_HTTPS_PORT if self.secure else DEFAULT_HTTP_PORT
        self.port = int(port)

        self.settings = {**DEFAULT_CLICKHOUSE_SETTINGS, **(settings or {})}
        self.settings.setdefault("max_execution_time", query_timeout)

        self._client = client

    # -- подключение --------------------------------------------------------

    @property
    def client(self):
        """Подключение создаётся при первом запросе, а не при создании объекта."""
        if self._client is not None:
            return self._client

        try:
            import clickhouse_connect
        except ImportError as error:
            raise DatabaseError(
                "Не установлен clickhouse-connect. Поставь: pip install clickhouse-connect"
            ) from error

        try:
            self._client = clickhouse_connect.get_client(
                host=self.host,
                port=self.port,
                username=self.user,
                password=self.password,
                database=self.database,
                secure=self.secure,
                verify=self.verify,
                connect_timeout=self.connect_timeout,
                send_receive_timeout=self.query_timeout,
                settings=self.settings,
            )
        except Exception as error:
            raise DatabaseError(
                f"Не удалось подключиться к ClickHouse "
                f"{self.host}:{self.port} (secure={self.secure}, "
                f"база {self.database!r}, пользователь {self.user!r}): {error}"
            ) from error

        return self._client

    # -- запросы ------------------------------------------------------------

    def fetch_df(self, query, params=None, settings=None):
        """
        Основной способ: сразу DataFrame с типами из ClickHouse.

        params — словарь. В запросе подставляются как {name:Тип}, например:
            SELECT * FROM t WHERE date >= {start:Date}
        Так безопаснее, чем склеивать строку.
        """
        _check_dialect(query, self.engine)
        started = time.monotonic()
        try:
            frame = self.client.query_df(
                query, parameters=params, settings=settings
            )
        except Exception as error:
            raise DatabaseError(self._explain(query, error)) from error

        frame.attrs["query_seconds"] = round(time.monotonic() - started, 2)
        return frame

    def fetch_all(self, query, params=None, settings=None):
        """
        Список словарей — как отдавал прежний класс из app/sql_oop.py.

        Оставлено для совместимости: pd.DataFrame(db.fetch_all(SQL)) работает
        без правок. На больших выгрузках медленнее fetch_df.
        """
        _check_dialect(query, self.engine)
        try:
            result = self.client.query(query, parameters=params, settings=settings)
        except Exception as error:
            raise DatabaseError(self._explain(query, error)) from error

        columns = result.column_names
        return [dict(zip(columns, row)) for row in result.result_rows]

    def execute(self, query, params=None):
        """Запрос без результата: INSERT, CREATE, ALTER."""
        try:
            return self.client.command(query, parameters=params)
        except Exception as error:
            raise DatabaseError(self._explain(query, error)) from error

    # -- разведка -----------------------------------------------------------

    def server_version(self):
        return self.execute("SELECT version()")

    def databases(self, include_system=False):
        """
        Какие базы вообще видно — когда имя базы неизвестно, начинать отсюда.

        ClickHouse показывает в system.* только то, на что у пользователя есть
        права. То есть это не «все базы сервера», а «все базы, доступные тебе» —
        для наших целей как раз то, что нужно.

        База без таблиц в system.tables не появится, поэтому имена берём из
        system.databases, а количества подставляем отдельно.
        """
        names = [
            row["name"]
            for row in self.fetch_all("SELECT name FROM system.databases ORDER BY name")
        ]
        if not include_system:
            names = [name for name in names if name not in SYSTEM_DATABASES]

        counts = {
            row["database"]: row
            for row in self.fetch_all(
                "SELECT database, count() AS tables, sum(total_rows) AS rows "
                "FROM system.tables GROUP BY database"
            )
        }

        return [
            {
                "name": name,
                "tables": (counts.get(name) or {}).get("tables", 0),
                "rows": (counts.get(name) or {}).get("rows", 0),
            }
            for name in names
        ]

    def find_table(self, pattern, include_system=False):
        """
        В какой базе лежит таблица — поиск по части имени во всех базах сразу.

        positionCaseInsensitive работает только с латиницей, но имена таблиц
        и так латинские, так что этого достаточно.
        """
        rows = self.fetch_all(
            "SELECT database, name, engine, total_rows FROM system.tables "
            "WHERE positionCaseInsensitive(name, {pattern:String}) > 0 "
            "ORDER BY database, name",
            {"pattern": pattern},
        )
        if not include_system:
            rows = [row for row in rows if row["database"] not in SYSTEM_DATABASES]
        return rows

    def tables(self, database=None):
        """Список таблиц базы."""
        rows = self.fetch_all(
            "SELECT name, engine, total_rows "
            "FROM system.tables WHERE database = {db:String} ORDER BY name",
            {"db": database or self.database},
        )
        return rows

    def columns(self, table, database=None):
        """Колонки таблицы с типами — по ним видно, где Nullable, а где нет."""
        return self.fetch_all(
            "SELECT name, type FROM system.columns "
            "WHERE database = {db:String} AND table = {tbl:String} "
            "ORDER BY position",
            {"db": database or self.database, "tbl": table},
        )

    def dry_run(self, query):
        """
        Проверяет запрос, не выполняя его: сервер разбирает SQL, находит
        таблицы и сверяет имена колонок.

        Именно EXPLAIN PLAN, а не EXPLAIN SYNTAX: второй только разбирает
        текст и на несуществующую колонку не ругается — проверено,
        см. scripts/db_test.py. А имена колонок здесь и есть главная
        засада: в MS SQL Server регистр не важен, в ClickHouse важен,
        и adID против adId — уже разные колонки.
        """
        self.execute(f"EXPLAIN PLAN {query}")
        return True

    def close(self):
        if self._client is not None:
            try:
                self._client.close()
            finally:
                self._client = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _explain(self, query, error):
        head = " ".join(str(query).split())[:200]
        return f"Запрос к ClickHouse не выполнился.\n  SQL: {head}…\n  Ошибка: {error}"


# ---------------------------------------------------------------------------
# MySQL — на время переезда
# ---------------------------------------------------------------------------

class MSSQLDatabase:
    """
    Прежняя база — Microsoft SQL Server через pyodbc.

    Нужна, чтобы во время миграции сверить выгрузки со старой базой и
    откатиться, если в ClickHouse что-то поедет. Повторяет поведение
    прежнего класса app.sql_oop.MySQL (название там осталось от более
    ранней версии, подключался он к SQL Server).
    """

    engine = "mssql"

    def __init__(self, host, user, password, database,
                 driver="ODBC Driver 17 for SQL Server", client=None):
        self.host = host
        self.user = user
        self.password = password
        self.database = database
        self.driver = driver
        self._client = client

    @property
    def client(self):
        if self._client is not None:
            return self._client

        try:
            import pyodbc
        except ImportError as error:
            raise DatabaseError(
                "Не установлен pyodbc. Поставь: pip install pyodbc"
            ) from error

        try:
            self._client = pyodbc.connect(
                f"DRIVER={{{self.driver}}};"
                f"SERVER={self.host};"
                f"DATABASE={self.database};"
                f"UID={self.user};"
                f"PWD={self.password};"
            )
        except Exception as error:
            raise DatabaseError(
                f"Не удалось подключиться к SQL Server {self.host}: {error}"
            ) from error

        return self._client

    def fetch_all(self, query, params=None, settings=None):
        _check_dialect(query, self.engine)
        cursor = self.client.cursor()
        try:
            cursor.execute(query, params) if params else cursor.execute(query)
            columns = [column[0] for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            cursor.close()

    def fetch_df(self, query, params=None, settings=None):
        return pd.DataFrame(self.fetch_all(query, params))

    def execute(self, query, params=None):
        cursor = self.client.cursor()
        try:
            cursor.execute(query, params) if params else cursor.execute(query)
            self.client.commit()
        finally:
            cursor.close()

    def close(self):
        if self._client is not None:
            try:
                self._client.close()
            finally:
                self._client = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# ---------------------------------------------------------------------------
# Фабрика
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# .env
# ---------------------------------------------------------------------------

#: Куда уже сходили за .env — чтобы не перечитывать при каждом подключении.
_ENV_FILE_LOADED = None

#: Незаполненные заготовки из .env.example. Если такое доехало до подключения,
#: значит .env скопировали, но не дозаполнили — и об этом лучше сказать прямо,
#: чем пытаться подключиться к хосту с именем "<хост>".
_PLACEHOLDERS = ("<", "…", "...")


def find_env_file(start=None):
    """
    Где лежит .env: сначала ENV_FILE, потом вверх от текущей папки, потом
    вверх от самого модуля. Второе нужно, когда скрипт запускают не из корня
    проекта, третье — когда модуль скопировали в другой проект.
    """
    explicit = os.getenv("ENV_FILE") or os.getenv("DOTENV_PATH")
    if explicit:
        return Path(explicit).expanduser()

    start = Path(start) if start else Path.cwd()
    here = Path(__file__).resolve()

    for directory in (start.resolve(), *start.resolve().parents, *here.parents):
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
    return None


def load_env_file(path=None, override=False):
    """
    Читает .env в переменные окружения. Возвращает путь или None.

    Раньше это делал только ноутбук, поэтому скрипты из scripts/ ничего в
    окружении не находили и падали на «Не задан адрес ClickHouse».

    override=False: то, что уже задано в окружении, не трогаем. Так работает
    разовая подмена без правки файла:
        CLICKHOUSE_DATABASE=media python scripts/dump_schema.py

    python-dotenv используется, если установлен; свой разбор оставлен, чтобы
    модуль можно было скопировать в другой проект без лишних зависимостей.
    """
    path = Path(path) if path else find_env_file()
    if path is None or not Path(path).is_file():
        return None

    try:
        from dotenv import load_dotenv
        load_dotenv(path, override=override)
        return Path(path)
    except ImportError:
        pass

    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()

        # Комментарий в конце строки — но только у незакавыченного значения:
        # в пароле решётка вполне может быть настоящим символом.
        if value[:1] in ("'", '"') and value[-1:] == value[:1] and len(value) > 1:
            value = value[1:-1]
        elif "#" in value:
            value = value.split("#", 1)[0].strip()

        if override or not os.getenv(key):
            os.environ[key] = value

    return Path(path)


def _ensure_env():
    """Загрузить .env один раз за процесс, перед первым обращением к настройкам."""
    global _ENV_FILE_LOADED
    if _ENV_FILE_LOADED is None:
        _ENV_FILE_LOADED = load_env_file() or False
    return _ENV_FILE_LOADED or None


def _looks_like_placeholder(value):
    return bool(value) and str(value).strip().startswith(_PLACEHOLDERS)


def _env(*names, default=None, profile=None):
    """
    Первое непустое значение из переменных окружения.

    profile — имя подключения, когда баз в проекте несколько. Тогда сперва
    ищутся переменные с приставкой: profile='x5' -> X5_CLICKHOUSE_HOST,
    и только потом общая CLICKHOUSE_HOST. Так в одном .env спокойно живут
    настройки нескольких баз, а проектам с одной базой ничего менять не надо.

    Значение, начинающееся с решётки, считается незаданным. Это не
    придирка, а защита от реальной ловушки python-dotenv: строка

        CLICKHOUSE_DATABASE=      # можно оставить пустым

    читается как база с именем "# можно оставить пустым", и дальше всё
    выглядит настроенным, просто не работает.
    """
    if profile:
        prefix = str(profile).strip().upper()
        names = (*[f"{prefix}_{name}" for name in names], *names)

    for name in names:
        value = os.getenv(name)
        if value in (None, "") or str(value).lstrip().startswith("#"):
            continue
        return value
    return default


def _as_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on", "да")


def _no_host_message(env_file, profile=None):
    """Понятная подсказка вместо «пропиши CLICKHOUSE_HOST» — где искали и что не так."""
    where = (f"{profile.upper()}_CLICKHOUSE_HOST или CLICKHOUSE_HOST"
             if profile else "CLICKHOUSE_HOST")

    if env_file is None:
        return (
            "Файл .env не найден — поэтому в окружении ничего нет.\n"
            f"  Искал вверх от {Path.cwd()} и от {Path(__file__).resolve().parent}.\n"
            "  Создай его в корне проекта:  cp .env.example .env  — и заполни\n"
            f"  {where} / CLICKHOUSE_USER / CLICKHOUSE_PASSWORD.\n"
            "  Путь можно задать и явно: ENV_FILE=/путь/к/.env"
        )

    return (
        f"В {env_file} нет {where} (или он пустой).\n"
        + (f"  Подключение запрошено с профилем {profile!r}: сначала ищется\n"
           f"  переменная с приставкой, потом общая.\n" if profile else "")
        + "  Проверь, что строка выглядит так:  CLICKHOUSE_HOST=ttk2.igronik.ru\n"
        "  Комментарий в конце строки с пустым значением станет значением —\n"
        "  пиши комментарии отдельными строками."
    )


def create_database(engine=None, profile=None, **overrides):
    """
    Собирает подключение по переменным окружения.

    engine : 'clickhouse' | 'mssql' | None (тогда берётся DB_ENGINE,
             по умолчанию clickhouse)
    profile: имя подключения, если баз в проекте несколько:

                 db_x5 = create_database(profile='x5')
                 db_digital = create_database(profile='digital')

             Переменные ищутся сначала с приставкой (X5_CLICKHOUSE_HOST),
             потом без неё. Для старой базы приставка ложится на прежние
             имена тоже: X5_SQL_SERVER, X5_SQL_USERNAME и так далее — то
             есть уже заполненный .env менять не нужно.

    Любой параметр можно передать явно — он перекроет окружение:
        create_database(host='localhost', port=8123, secure=False)
    """
    env_file = _ensure_env()
    engine = (engine or _env("DB_ENGINE", profile=profile,
                             default="clickhouse")).strip().lower()

    if engine in ("clickhouse", "ch"):
        secure = _env("CLICKHOUSE_SECURE", "CH_SECURE", profile=profile)
        config = {
            "host": _env("CLICKHOUSE_HOST", "CH_HOST", "HOST", profile=profile),
            "port": _env("CLICKHOUSE_PORT", "CH_PORT", profile=profile),
            "user": _env("CLICKHOUSE_USER", "CH_USER", profile=profile,
                         default="default"),
            "password": _env("CLICKHOUSE_PASSWORD", "CH_PASSWORD", "PASSWORD",
                             profile=profile, default=""),
            "database": _env("CLICKHOUSE_DATABASE", "CH_DATABASE", "DB_NAME",
                             profile=profile, default="default"),
            "secure": _as_bool(secure, default=None) if secure is not None else None,
            "verify": _as_bool(_env("CLICKHOUSE_VERIFY", profile=profile), default=True),
        }
        config.update(overrides)

        if not config.get("host"):
            raise DatabaseError(_no_host_message(env_file, profile))

        # Заготовки вида <хост> из .env.example: подключаться с ними
        # бессмысленно, а ошибка драйвера была бы про DNS.
        placeholders = [
            f"CLICKHOUSE_{key.upper()}={value}"
            for key, value in config.items()
            if _looks_like_placeholder(value)
        ]
        if placeholders:
            raise DatabaseError(
                "В .env остались незаполненные заготовки:\n  "
                + "\n  ".join(placeholders)
                + f"\nФайл: {env_file or '(не найден)'}"
            )

        return ClickHouseDatabase(**config)

    if engine in ("mssql", "sqlserver", "mysql"):
        # SQL_SERVER / SQL_USERNAME и прочие — имена, принятые в соседних
        # проектах (X5_SQL_SERVER, DIGITAL_SQL_SERVER). Перечислены здесь,
        # чтобы уже заполненный .env работал без переименований.
        config = {
            "host": _env("MSSQL_HOST", "SQL_SERVER", "HOST", profile=profile),
            "user": _env("MSSQL_USER", "SQL_USERNAME", "DB_USER", "USER",
                         profile=profile),
            "password": _env("MSSQL_PASSWORD", "SQL_PASSWORD", "PASSWORD",
                             profile=profile, default=""),
            "database": _env("MSSQL_DATABASE", "SQL_DATABASE", "DB_NAME",
                             profile=profile),
        }
        config.update(overrides)
        return MSSQLDatabase(**config)

    raise DatabaseError(
        f"Неизвестный движок базы: {engine!r}. Ожидается 'clickhouse' или 'mssql'."
    )


def connect_for_discovery(engine=None, profile=None, **overrides):
    """
    Подключение, когда имя базы ещё неизвестно или указано неверно.

    Подключиться к ClickHouse, не назвав базу, нельзя — но чтобы посмотреть
    список баз и таблиц, годится любая доступная: system.* видно отовсюду.
    Поэтому пробуем по очереди: то, что задано в .env, потом default, потом
    system. Первое, где реально проходит запрос, и берём.

    Возвращает (db, отвергнутые), где отвергнутые — список пар
    (имя базы, текст ошибки). Если он не пуст, а подключение получилось,
    значит имя базы в .env неверное — и это ровно тот случай, ради которого
    функция и написана.
    """
    _ensure_env()
    configured = overrides.pop("database", None) or _env(
        "CLICKHOUSE_DATABASE", "CH_DATABASE", "DB_NAME", profile=profile
    )

    candidates = [name for name in (configured, *DISCOVERY_DATABASES) if name]
    seen, ordered = set(), []
    for name in candidates:
        if name not in seen:
            seen.add(name)
            ordered.append(name)

    rejected = []
    for name in ordered:
        db = create_database(engine, profile=profile, database=name, **overrides)
        try:
            # Ленивое подключение: пока не сделан запрос, ошибки не будет.
            db.execute("SELECT 1")
            return db, rejected
        except Exception as error:
            rejected.append((name, str(error).split("\n")[0][:200]))
            db.close()

    raise DatabaseError(
        "Не удалось подключиться ни к одной базе.\n  "
        + "\n  ".join(f"{name}: {message}" for name, message in rejected)
    )


def describe_environment():
    """
    Что видно в окружении — без паролей. Для диагностики «почему не подключается».

    Отдельно предупреждает про USER: на Linux эта переменная почти всегда уже
    занята именем пользователя системы, и os.getenv('USER') вернёт его, а не
    логин к базе, если в .env своего значения нет.
    """
    env_file = _ensure_env()
    engine = _env("DB_ENGINE", default="clickhouse")

    report = {
        "файл .env": str(env_file) if env_file else "не найден",
        "DB_ENGINE": engine,
        "CLICKHOUSE_HOST": _env("CLICKHOUSE_HOST", "CH_HOST", "HOST"),
        "CLICKHOUSE_PORT": _env("CLICKHOUSE_PORT", "CH_PORT", default="(по secure)"),
        "CLICKHOUSE_USER": _env("CLICKHOUSE_USER", "CH_USER", default="default"),
        "CLICKHOUSE_DATABASE": _env("CLICKHOUSE_DATABASE", "CH_DATABASE", "DB_NAME"),
        "CLICKHOUSE_SECURE": _env("CLICKHOUSE_SECURE", "CH_SECURE", default="(по порту)"),
        "пароль задан": bool(_env("CLICKHOUSE_PASSWORD", "CH_PASSWORD", "PASSWORD")),
    }

    warnings = []
    if env_file is None:
        warnings.append(
            "Файл .env не найден — всё, что ниже, взято из переменных окружения. "
            "Создай его в корне проекта: cp .env.example .env"
        )
    if os.getenv("USER") and not os.getenv("CLICKHOUSE_USER") and not os.getenv("DB_USER"):
        warnings.append(
            f"Переменная USER = {os.getenv('USER')!r} — это имя пользователя системы, "
            f"а не логин к базе. Задай CLICKHOUSE_USER явно."
        )
    for key, value in report.items():
        if _looks_like_placeholder(value):
            warnings.append(f"{key} = {value!r} — это заготовка из .env.example, замени.")

    report["предупреждения"] = warnings
    return report

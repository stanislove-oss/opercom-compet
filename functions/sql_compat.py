"""
Что сломается в запросах при переезде MS SQL Server -> ClickHouse.

Модуль самодостаточный: копируется в другие проекты как есть.

Правила не выдуманы, а проверены на настоящем движке ClickHouse
(chdb, ядро 26.7) — см. scripts/db_test.py, там каждое правило подтверждается
запросом: «так падает / так работает».

Автоматически запросы НЕ переписываются. Половина отличий — не синтаксис,
а другой РЕЗУЛЬТАТ на том же синтаксисе, и молча их «чинить» опаснее, чем
показать человеку. Поэтому здесь разбор с объяснением, а правку делает автор
запроса.

    from functions.sql_compat import check_sql, format_report

    print(format_report(check_sql(TV_SQL, name='TV_SQL')))
"""

import re

SEVERITY_ERROR = "падает"
SEVERITY_SILENT = "тихо меняет результат"
SEVERITY_NOTE = "стоит посмотреть"

#: Порядок важности при выводе.
SEVERITY_ORDER = {SEVERITY_ERROR: 0, SEVERITY_SILENT: 1, SEVERITY_NOTE: 2}


class Rule:
    """
    uses_literals : искать ли внутри строковых литералов.

        По умолчанию литералы замазываются. Иначе ловятся ложные срабатывания:
        в 'ALL_18+' плюс — часть названия аудитории, а не склейка строк.
        Правилам, которые как раз смотрят на содержимое литерала (кириллица
        в LIKE, удвоенные проценты), литералы нужны — им ставится True.
    """

    def __init__(self, code, pattern, severity, what, why, fix,
                 flags=re.IGNORECASE, uses_literals=False):
        self.code = code
        self.pattern = re.compile(pattern, flags)
        self.severity = severity
        self.what = what
        self.why = why
        self.fix = fix
        self.uses_literals = uses_literals

    def find(self, sql):
        return [m for m in self.pattern.finditer(sql)]


RULES = [
    # ---------------- падает ----------------
    Rule(
        "datediff",
        r"\bDATEDIFF\s*\(\s*(?!')[A-Za-z_]",
        SEVERITY_ERROR,
        "DATEDIFF в синтаксисе SQL Server",
        "В SQL Server единица измерения пишется голым словом: "
        "DATEDIFF(day, начало, конец). ClickHouse ждёт её строкой: "
        "dateDiff('day', начало, конец). Двухаргументная форма (как в MySQL) "
        "тоже не работает, и там вдобавок обратный порядок дат.",
        "DATEDIFF(day, a, b)  ->  dateDiff('day', a, b)",
    ),
    Rule(
        "top_n",
        r"\bSELECT\s+(DISTINCT\s+)?TOP\s+\d+",
        SEVERITY_ERROR,
        "SELECT TOP n",
        "Конструкции TOP в ClickHouse нет.",
        "SELECT TOP 100 ...  ->  SELECT ... LIMIT 100",
    ),
    Rule(
        "brackets",
        r"\[[A-Za-z_][\w ]*\]",
        SEVERITY_ERROR,
        "Имена в квадратных скобках",
        "Так экранирует имена SQL Server. ClickHouse понимает только "
        "обратные кавычки или двойные.",
        "[Ad Id]  ->  `Ad Id`",
    ),
    Rule(
        "odbc_placeholder",
        r"(?<![\w'])\?(?![\w'])",
        SEVERITY_ERROR,
        "Плейсхолдеры pyodbc (?)",
        "Новый драйвер их не подставляет, и знак вопроса остаётся в тексте "
        "запроса синтаксической ошибкой.",
        "WHERE d >= ?  ->  WHERE d >= {start:Date}, "
        "дальше db.fetch_df(SQL, {'start': date})",
    ),
    Rule(
        "getdate",
        r"\bGETDATE\s*\(\s*\)|\bSYSDATETIME\s*\(\s*\)",
        SEVERITY_ERROR,
        "GETDATE() / SYSDATETIME()",
        "Функций SQL Server с такими именами в ClickHouse нет.",
        "GETDATE()  ->  now(),   для даты — today()",
    ),
    Rule(
        "isnull",
        r"\bISNULL\s*\(",
        SEVERITY_ERROR,
        "ISNULL",
        "В ClickHouse функция называется иначе, а isNull(x) там значит "
        "совсем другое — «является ли x пустым», с одним аргументом.",
        "ISNULL(a, b)  ->  ifNull(a, b)",
    ),
    Rule(
        "charindex_len",
        r"\bCHARINDEX\s*\(|\bLEN\s*\(",
        SEVERITY_ERROR,
        "CHARINDEX / LEN",
        "Таких функций в ClickHouse нет. У замены CHARINDEX ОБРАТНЫЙ порядок "
        "аргументов: CHARINDEX(что, где) против position(где, что).",
        "CHARINDEX(a, b) -> position(b, a),   LEN(x) -> lengthUTF8(x)",
    ),
    Rule(
        "string_concat_plus",
        r"'[^']*'\s*\+\s*|\+\s*'[^']*'",
        SEVERITY_ERROR,
        "Склейка строк через +",
        "В ClickHouse плюс — только сложение чисел.",
        "a + b  ->  concat(a, b)",
    ),
    Rule(
        "union_all",
        r"\bUNION\b(?!\s+(ALL|DISTINCT)\b)",
        SEVERITY_ERROR,
        "UNION без ALL или DISTINCT",
        "ClickHouse требует явно указать, отбрасывать ли дубли.",
        "UNION  ->  UNION DISTINCT (так же, как понимает UNION SQL Server) "
        "либо UNION ALL, если ветки заведомо не пересекаются — так быстрее",
    ),
    Rule(
        "placeholder",
        r"%s|%\(\w+\)s",
        SEVERITY_ERROR,
        "Плейсхолдеры в стиле pymysql (%s)",
        "clickhouse-connect подставляет параметры иначе, и %s остаётся в тексте "
        "запроса — ClickHouse спотыкается на нём как на синтаксической ошибке.",
        "WHERE d >= %s  ->  WHERE d >= {start:Date}, "
        "дальше db.fetch_df(SQL, {'start': date})",
    ),
    Rule(
        "string_arithmetic",
        r"'\s*\d+\s*'\s*[-+*/]|[-+*/]\s*'\s*\d+\s*'",
        SEVERITY_ERROR,
        "Арифметика со строкой-числом",
        "SQL Server сам превращает '5' в 5, ClickHouse — нет, и запрос падает.",
        "'5' + 1  ->  toInt32('5') + 1",
        uses_literals=True,
    ),

    # ---------------- тихо меняет результат ----------------
    Rule(
        "lower_cyrillic",
        r"\b(LOWER|UPPER)\s*\(",
        SEVERITY_SILENT,
        "LOWER / UPPER на кириллице",
        "Эти функции в ClickHouse работают только с латиницей. "
        "lower('БАНК') вернёт 'БАНК' без изменений — запрос не упадёт, "
        "но сравнение и группировка по названиям брендов молча развалятся.",
        "LOWER(x)  ->  lowerUTF8(x),   UPPER(x)  ->  upperUTF8(x)",
    ),
    Rule(
        "substring_cyrillic",
        r"\b(SUBSTRING|SUBSTR|LEFT|RIGHT|LENGTH)\s*\(",
        SEVERITY_SILENT,
        "Работа с подстрокой на кириллице",
        "Эти функции считают БАЙТЫ, а не символы. На кириллице режут символ "
        "пополам и портят строку.",
        "SUBSTRING(x,2,2)  ->  substringUTF8(x,2,2),  LENGTH  ->  lengthUTF8",
    ),
    Rule(
        "like_case",
        r"\bLIKE\s+'[^']*[А-Яа-яЁё][^']*'",
        SEVERITY_SILENT,
        "LIKE с русским текстом",
        "В SQL Server со стандартной сортировкой LIKE не различает регистр, "
        "в ClickHouse различает. LIKE '%банк%' перестанет находить «Банк» и «БАНК».",
        "LIKE '%банк%'  ->  ILIKE '%банк%'  либо  lowerUTF8(x) LIKE '%банк%'",
        uses_literals=True,
    ),
    Rule(
        "left_join_nulls",
        r"\b(LEFT|RIGHT|FULL)\s+(OUTER\s+)?JOIN\b",
        SEVERITY_SILENT,
        "Внешний JOIN",
        "Там, где в SQL Server было бы NULL, ClickHouse по умолчанию подставляет "
        "значение по умолчанию типа: 0 для чисел и пустую строку для текста. "
        "Проверки вида «WHERE b.col IS NULL» перестают срабатывать, а нули "
        "попадают в суммы и средние.",
        "Слой доступа включает join_use_nulls=1 — поведение становится как в "
        "SQL Server. Если запрос выполняется мимо него, добавь в конец "
        "SETTINGS join_use_nulls = 1",
    ),
    Rule(
        "agg_on_empty",
        r"\b(SUM|AVG|MAX|MIN)\s*\(",
        SEVERITY_NOTE,
        "Агрегаты на пустом наборе",
        "Если строк не осталось, SQL Server вернёт NULL, а ClickHouse — 0 для sum "
        "и count, nan для avg, 0 для max. Условия «IS NULL» после агрегатов "
        "работать перестанут.",
        "Проверяй через count() > 0, а не через «результат IS NULL»",
    ),
    Rule(
        "division",
        r"/\s*(?!\*)[A-Za-z_`\"(]",
        SEVERITY_NOTE,
        "Деление на выражение",
        "Деление на ноль в SQL Server даёт ошибку или NULL, в ClickHouse — inf или nan. "
        "Эти значения дойдут до pandas и испортят суммы и округления.",
        "a / b  ->  if(b = 0, 0, a / b)  либо  intDivOrZero(a, b)",
    ),

    # ---------------- стоит посмотреть ----------------
    Rule(
        "double_percent",
        r"'%%[^']*'|'[^']*%%'",
        SEVERITY_NOTE,
        "Удвоенные проценты в LIKE",
        "Так пишут, когда запрос идёт через драйвер, который съедает один "
        "процент. ClickHouse ничего не съедает, и %% остаётся двумя "
        "подстановочными знаками. Обычно безобидно, но выдаёт запрос, "
        "не адаптированный под новый драйвер.",
        "'%%банк%%'  ->  '%банк%'",
        uses_literals=True,
    ),
    Rule(
        "backticks",
        r"`\w+`",
        SEVERITY_NOTE,
        "Обратные кавычки",
        "ClickHouse их понимает, менять не обязательно. Отмечено только чтобы "
        "не удивляться при чтении диффа.",
        "можно оставить как есть",
    ),
]


def strip_comments(sql):
    """Убирает комментарии, чтобы не ловить правила в пояснениях."""
    sql = re.sub(r"--[^\n]*", " ", sql)
    return re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)


def mask_string_literals(sql, filler="\u00b7"):
    """
    Замазывает содержимое строковых литералов, сохраняя длину и кавычки.

    Нужно, чтобы правила не срабатывали на том, что внутри кавычек: плюс
    в 'ALL_18+' — это часть названия аудитории, а не склейка строк.
    Длина сохраняется, поэтому номера строк и позиции остаются верными.
    """
    return re.sub(r"'([^']*)'", lambda m: "'" + filler * len(m.group(1)) + "'", sql)


# Оставлено под прежним именем: на него могли ссылаться в других проектах.
def strip_comments_and_strings(sql, keep_strings=True):
    sql = strip_comments(sql)
    return sql if keep_strings else mask_string_literals(sql)


_ALIAS_RE = re.compile(r"\bAS\s+([A-Za-z_][A-Za-z_0-9]*)", re.IGNORECASE)


def find_alias_shadowing(sql):
    """
    Ищет псевдонимы из SELECT, которые повторяют имя колонки и при этом
    используются в WHERE.

    В ClickHouse псевдоним из SELECT ВИДЕН в WHERE, в SQL Server — нет.
    Поэтому запрос вида

        SELECT lowerUTF8(media_type_long) AS media_type ...
        WHERE media_type = 'TV'

    сравнивает не колонку, а псевдоним: 'tv' с 'TV'. Ошибки нет, просто
    молча возвращается ноль строк. Лечится обращением через псевдоним
    таблицы: FROM t AS mc ... WHERE mc.media_type = 'TV'.
    """
    cleaned = mask_string_literals(strip_comments(sql))

    where = re.search(
        r"\bWHERE\b(.*?)(?=\bGROUP\s+BY\b|\bORDER\s+BY\b|\bHAVING\b"
        r"|\bLIMIT\b|\bUNION\b|\bSETTINGS\b|$)",
        cleaned, re.IGNORECASE | re.DOTALL)
    if not where:
        return []

    where_text = where.group(1)

    # Псевдонимы берём только из списка SELECT: «FROM t AS mc» — это имя
    # таблицы, оно как раз и есть лекарство, а не болезнь.
    select_part = re.search(r"\bSELECT\b(.*?)\bFROM\b", cleaned,
                            re.IGNORECASE | re.DOTALL)
    if not select_part:
        return []

    aliases = {a.lower() for a in _ALIAS_RE.findall(select_part.group(1))}

    # Имена в WHERE без префикса таблицы: «mc.media_type» не считается,
    # там уже указано, откуда брать колонку.
    bare = {
        word.lower()
        for word in re.findall(
            r"(?<![\w.])([A-Za-z_][A-Za-z_0-9]*)(?!\s*\.)", where_text)
        if word.lower() not in _SQL_KEYWORDS
    }

    return sorted(aliases & bare)


def check_sql(sql, name=None, rules=None):
    """
    Разбирает один запрос. Возвращает список находок:
        {"name", "code", "severity", "what", "why", "fix", "fragment", "line"}
    """
    rules = RULES if rules is None else rules

    with_literals = strip_comments(sql)
    without_literals = mask_string_literals(with_literals)

    findings = []
    for rule in rules:
        text = with_literals if rule.uses_literals else without_literals
        for match in rule.find(text):
            line = text.count("\n", 0, match.start()) + 1
            findings.append({
                "name": name,
                "code": rule.code,
                "severity": rule.severity,
                "what": rule.what,
                "why": rule.why,
                "fix": rule.fix,
                "fragment": " ".join(match.group(0).split())[:80],
                "line": line,
            })

    for alias in find_alias_shadowing(sql):
        findings.append({
            "name": name,
            "code": "alias_shadowing",
            "severity": SEVERITY_SILENT,
            "what": "псевдоним из SELECT используется в WHERE",
            "why": "В ClickHouse псевдонимы из SELECT видны в WHERE, в SQL Server "
                   "нет. Условие сравнивает не колонку, а вычисленное выражение: "
                   "например lowerUTF8(media_type_long) вместо media_type, то есть "
                   "'tv' вместо 'TV'. Ошибки не будет — запрос молча вернёт ноль "
                   "строк.",
            "fix": "Обращаться к колонке через псевдоним таблицы: "
                   "FROM t AS mc ... WHERE mc.<колонка> = ...",
            "fragment": alias,
            "line": 1,
        })

    findings.sort(key=lambda f: (SEVERITY_ORDER[f["severity"]], f["line"]))
    return findings


def check_queries(queries, rules=None):
    """
    Разбирает все запросы проекта.

    queries : dict {имя: sql} либо модуль — тогда берутся все строковые
              константы в ВЕРХНЕМ РЕГИСТРЕ, похожие на SQL.
    """
    if not isinstance(queries, dict):
        queries = collect_queries(queries)

    result = {}
    for name, sql in queries.items():
        result[name] = check_sql(sql, name=name, rules=rules)
    return result


#: Слова, которые не являются именами колонок.
_SQL_KEYWORDS = {
    "select", "from", "where", "group", "by", "order", "having", "join", "left",
    "right", "inner", "outer", "full", "on", "as", "and", "or", "not", "in",
    "union", "all", "distinct", "sum", "count", "avg", "min", "max", "lower",
    "upper", "case", "when", "then", "else", "end", "null", "is", "like", "asc",
    "desc", "limit", "top", "settings", "with", "over", "partition",
}


def check_identifier_case(queries):
    """
    Ищет имена, различающиеся ТОЛЬКО регистром: adId и adID.

    В SQL Server регистр имён не важен, и такие расхождения живут в запросах
    незамеченными годами. В ClickHouse это разные колонки, и неверное
    написание даёт «Unknown expression identifier».

    Проверка идёт по всем запросам сразу: расхождение обычно между разными
    запросами, а не внутри одного.
    """
    seen = {}

    for name, sql in queries.items():
        cleaned = mask_string_literals(strip_comments(sql))
        for word in re.findall(r"\b[A-Za-z_][A-Za-z_0-9]*\b", cleaned):
            if word.lower() in _SQL_KEYWORDS:
                continue
            seen.setdefault(word.lower(), {}).setdefault(word, set()).add(name)

    conflicts = []
    for lowered, variants in seen.items():
        if len(variants) < 2:
            continue
        conflicts.append({
            "identifier": lowered,
            "variants": {form: sorted(where) for form, where in sorted(variants.items())},
        })

    return sorted(conflicts, key=lambda c: c["identifier"])


def format_identifier_case(conflicts):
    if not conflicts:
        return "  расхождений по регистру имён нет\n"

    lines = [
        "  В ClickHouse имена колонок регистрозависимы, в SQL Server — нет.",
        "  Ниже имена, которые в запросах написаны по-разному. Верное",
        "  написание можно посмотреть на сервере:",
        "      python scripts/check_clickhouse.py --table <таблица>",
        "",
    ]
    for item in conflicts:
        lines.append(f"    {item['identifier']}:")
        for form, where in item["variants"].items():
            lines.append(f"      {form:<28} в {', '.join(where)}")
    return "\n".join(lines) + "\n"


def collect_queries(module):
    """
    Достаёт из модуля константы, похожие на SQL-запросы.

    Имена с подчёркиванием в начале пропускаются: это служебные заготовки
    (например, _COST_TEMPLATE с подстановками {media_type}), а не готовые
    запросы — выполнять их нельзя.
    """
    found = {}
    for name in dir(module):
        if name.startswith("_") or not name.isupper():
            continue
        value = getattr(module, name)
        if isinstance(value, str) and re.search(r"\bSELECT\b", value, re.IGNORECASE):
            found[name] = value
    return found


def format_report(findings, show_why=True):
    """Человекочитаемый разбор."""
    if isinstance(findings, dict):
        lines = []
        for name, items in findings.items():
            lines.append(format_report(items, show_why=show_why) if items
                         else f"=== {name} ===\n  чисто\n")
        return "\n".join(lines)

    if not findings:
        return "  чисто\n"

    name = findings[0].get("name")
    lines = [f"=== {name} ===" if name else "==="]

    by_severity = {}
    for item in findings:
        by_severity.setdefault(item["severity"], []).append(item)

    for severity in sorted(by_severity, key=lambda s: SEVERITY_ORDER[s]):
        items = by_severity[severity]
        lines.append(f"\n  [{severity}]")

        shown = set()
        for item in items:
            if item["code"] in shown:
                continue
            shown.add(item["code"])

            count = sum(1 for i in items if i["code"] == item["code"])
            times = f" ({count} шт.)" if count > 1 else ""
            lines.append(f"    {item['what']}{times}")
            lines.append(f"      нашлось: {item['fragment']}")
            if show_why:
                for line in _wrap(item["why"], 76):
                    lines.append(f"      {line}")
            lines.append(f"      как быть: {item['fix']}")

    return "\n".join(lines) + "\n"


def _wrap(text, width):
    words, line, out = text.split(), "", []
    for word in words:
        if len(line) + len(word) + 1 > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(line)
    return out


def summarize(report):
    """Сводка по всем запросам: сколько чего нашлось."""
    counts = {SEVERITY_ERROR: 0, SEVERITY_SILENT: 0, SEVERITY_NOTE: 0}
    for findings in report.values():
        for item in findings:
            counts[item["severity"]] += 1
    return counts

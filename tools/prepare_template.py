def print_slide_objects(presentation, slide_num, only_charts_and_tables=True):
    """
    Диагностика объектов на слайде.
    Помогает быстро понять, как называются charts/tables/textboxes в шаблоне.
    """
    slide = presentation.slides[slide_num - 1]
    chart_count = 0
    table_count = 0

    for shape in iter_all_shapes(slide.shapes):
        has_chart = bool(getattr(shape, "has_chart", False))
        has_table = bool(getattr(shape, "has_table", False))
        has_text = bool(getattr(shape, "has_text_frame", False))

        if has_chart:
            chart_count += 1
        if has_table:
            table_count += 1

        if only_charts_and_tables and not (has_chart or has_table):
            continue

        kind = []
        if has_chart:
            kind.append(f"CHART #{chart_count}")
        if has_table:
            kind.append(f"TABLE #{table_count}")
        if has_text and not (has_chart or has_table):
            kind.append("TEXT")

        print(
            f"slide={slide_num}",
            f"name={shape.name!r}",
            f"shape_id={shape.shape_id}",
            f"left={shape.left}",
            f"top={shape.top}",
            f"width={shape.width}",
            f"height={shape.height}",
            " | ".join(kind),
        )


def rename_shape(presentation, slide_num, old_name=None, new_name=None, shape_id=None):
    """
    Переименовывает shape в шаблоне/презентации.
    Можно искать либо по old_name, либо по shape_id.
    """
    slide = presentation.slides[slide_num - 1]

    for shape in iter_all_shapes(slide.shapes):
        if shape_id is not None and shape.shape_id == shape_id:
            shape.name = new_name
            return shape

        if old_name is not None and shape.name == old_name:
            shape.name = new_name
            return shape

    raise ValueError(
        f"Shape not found on slide {slide_num}: "
        f"old_name={old_name!r}, shape_id={shape_id!r}"
    )


def rename_shapes_by_map(presentation, rename_map):
    """
    Массовое переименование shapes.

    rename_map пример:
    [
        {"slide": 2, "shape_id": 10, "new_name": "chart__slide_total_dynamic_year"},
        {"slide": 2, "old_name": "Chart 5", "new_name": "chart__slide_total_dynamic_q"},
    ]
    """
    renamed = []

    for item in rename_map:
        shape = rename_shape(
            presentation=presentation,
            slide_num=item["slide"],
            old_name=item.get("old_name"),
            shape_id=item.get("shape_id"),
            new_name=item["new_name"],
        )
        renamed.append((item["slide"], shape.shape_id, shape.name))

    return renamed
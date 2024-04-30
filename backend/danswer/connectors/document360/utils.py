def flatten_child_categories(category: dict) -> list[dict]:
    if not category["child_categories"]:
        return [category]
    else:
        flattened_categories = [category]
        for child_category in category["child_categories"]:
            flattened_categories.extend(flatten_child_categories(child_category))
        return flattened_categories

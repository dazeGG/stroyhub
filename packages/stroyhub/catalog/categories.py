from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stroyhub.models.tables import Category, SourceProduct


@dataclass(kw_only=True)
class CategoryTreeItem:
    id: int
    slug: str
    name: str
    parent_id: int | None
    product_count: int
    children: list["CategoryTreeItem"] = field(default_factory=list)


class CategoryCatalog:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_tree(self) -> list[CategoryTreeItem]:
        categories = list(
            self._session.scalars(
                select(Category).order_by(
                    Category.parent_id.asc().nullsfirst(),
                    Category.name.asc(),
                    Category.id.asc(),
                )
            )
        )
        if not categories:
            return []

        direct_counts: dict[int, int] = {}
        count_rows = self._session.execute(
            select(SourceProduct.category_id, func.count(SourceProduct.id))
            .where(
                SourceProduct.is_active.is_(True),
                SourceProduct.category_id.is_not(None),
            )
            .group_by(SourceProduct.category_id)
        )
        for category_id, product_count in count_rows:
            if category_id is not None:
                direct_counts[category_id] = product_count

        items_by_id = {
            category.id: CategoryTreeItem(
                id=category.id,
                slug=category.slug,
                name=category.name,
                parent_id=category.parent_id,
                product_count=int(direct_counts.get(category.id, 0)),
            )
            for category in categories
        }

        roots: list[CategoryTreeItem] = []
        for category in categories:
            item = items_by_id[category.id]
            if category.parent_id is None:
                roots.append(item)
                continue

            parent = items_by_id.get(category.parent_id)
            if parent is None:
                roots.append(item)
            else:
                parent.children.append(item)

        for root in roots:
            self._roll_up_product_count(root)

        return roots

    def _roll_up_product_count(self, item: CategoryTreeItem) -> int:
        item.product_count += sum(
            self._roll_up_product_count(child) for child in item.children
        )
        return item.product_count

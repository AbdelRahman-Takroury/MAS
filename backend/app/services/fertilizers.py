"""Verified Jordan retail fertilizer listings; price snapshot, not agronomic advice."""
from datetime import date

CATALOG_UPDATED = date(2026, 10, 10).isoformat()
CATALOG_SOURCE = "Taha & Qashou Agriculture Co., Amman, Jordan"

# Retail listing values captured from the linked supplier pages on CATALOG_UPDATED.
# This static snapshot is intentionally explicit; it is not an official wholesale tariff.
PRODUCTS = [
    {
        "id": "masterblend-20-20-20-1kg", "name": "NPK 20-20-20 Masterblend",
        "name_ar": "ماستربلند NPK 20-20-20", "analysis": "20-20-20",
        "package_quantity": 1, "package_unit": "kg", "price_jod": 5.50,
        "price_per_kg_jod": 5.50, "source": CATALOG_SOURCE,
        "source_url": "https://tahaandqashou.net/product/npk-20-20-20-masterblend-1-kg/",
        "source_updated": CATALOG_UPDATED,
        "source_fit": "Supplier lists vegetables and open-field cultivation.",
        "source_fit_ar": "المورد يذكر الخضروات والزراعة في الحقول المفتوحة.",
        "profile": "Equal N, P₂O₅ and K₂O percentages; water-soluble; micronutrients listed.",
        "profile_ar": "نسب متساوية من N وP₂O₅ وK₂O؛ ذائب بالماء؛ يذكر المورد عناصر صغرى.",
    },
    {
        "id": "masterblend-17-10-27-1kg", "name": "NPK 17-10-27 Masterblend",
        "name_ar": "ماستربلند NPK 17-10-27", "analysis": "17-10-27",
        "package_quantity": 1, "package_unit": "kg", "price_jod": 5.50,
        "price_per_kg_jod": 5.50, "source": CATALOG_SOURCE,
        "source_url": "https://tahaandqashou.net/product/npk-17-10-27-masterblend-1-kg/",
        "source_updated": CATALOG_UPDATED,
        "source_fit": "Supplier describes drip, hydroponic and foliar use; no tomato-specific fit stated.",
        "source_fit_ar": "يذكر المورد الري بالتنقيط والزراعة المائية والرش الورقي؛ ولا يحدد ملاءمة خاصة للطماطم.",
        "profile": "N 17%, P₂O₅ 10%, K₂O 27%; water-soluble; micronutrients listed.",
        "profile_ar": "N بنسبة 17% وP₂O₅ بنسبة 10% وK₂O بنسبة 27%؛ ذائب بالماء؛ يذكر عناصر صغرى.",
    },
    {
        "id": "masterblend-12-12-36-1kg", "name": "NPK 12-12-36 Masterblend",
        "name_ar": "ماستربلند NPK 12-12-36", "analysis": "12-12-36",
        "package_quantity": 1, "package_unit": "kg", "price_jod": 5.50,
        "price_per_kg_jod": 5.50, "source": CATALOG_SOURCE,
        "source_url": "https://tahaandqashou.net/product/npk-12-12-36-masterblend-1kg/",
        "source_updated": CATALOG_UPDATED,
        "source_fit": "Supplier describes drip and foliar use, and mentions flowering/fruiting; not a farm-specific recommendation.",
        "source_fit_ar": "يذكر المورد الري بالتنقيط والرش والإزهار والإثمار؛ وهذا ليس توصية خاصة بالمزرعة.",
        "profile": "N 12%, P₂O₅ 12%, K₂O 36%; water-soluble; micronutrients listed.",
        "profile_ar": "N بنسبة 12% وP₂O₅ بنسبة 12% وK₂O بنسبة 36%؛ ذائب بالماء؛ يذكر عناصر صغرى.",
    },
]


def catalog_response():
    return {
        "origin": "supplier_snapshot",
        "updated_at": CATALOG_UPDATED,
        "source": CATALOG_SOURCE,
        # Avoid sharing mutable per-farm budget-comparison fields across requests.
        "products": [dict(product) for product in PRODUCTS],
        "notice": "Retail listing snapshot; confirm current price, availability, and label before purchase. No dose or agronomic recommendation is provided.",
        "notice_ar": "لقطة من أسعار التجزئة المنشورة؛ تحقّق من السعر والتوفر والملصق قبل الشراء. لا تتضمن جرعات أو توصية زراعية.",
    }

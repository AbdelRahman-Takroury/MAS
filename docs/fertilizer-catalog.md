# Fertilizer catalog and price comparison

The dashboard reads `GET /api/farms/{farm_id}/fertilizers`. The catalog is a small, dated server-side snapshot; it does not add database tables, create purchase/expense records, estimate application rates, or make nutrient recommendations.

## Source and update policy

The listed products and JOD retail prices were checked on 2026-10-10 against product pages from Taha & Qashou Agriculture Co. in Amman:

- [NPK 20-20-20 Masterblend, 1 kg](https://tahaandqashou.net/product/npk-20-20-20-masterblend-1-kg/)
- [NPK 17-10-27 Masterblend, 1 kg](https://tahaandqashou.net/product/npk-17-10-27-masterblend-1-kg/)
- [NPK 12-12-36 Masterblend, 1 kg](https://tahaandqashou.net/product/npk-12-12-36-masterblend-1kg/)

Each listed product was displayed at JOD 5.50 per 1 kg package when checked. The API reports the source and snapshot date with each product. It does not claim those prices or stock are live; check the supplier page or contact the seller before purchase. The product descriptions and nutrient analyses are supplier claims, not independent laboratory verification.

Jordan's Department of Statistics describes an annual survey of production-input prices, including chemical and organic fertilizer prices, in its [agricultural prices methodology](https://dosweb.gov.jo/ar/agriculture/agricultural-prices/). Its current interactive table does not expose a usable current item-level value in this implementation, so the app does not present official DoS prices as retail quotes.

## Comparison semantics

- Package cost is the supplier's listed package price. Unit cost is package price divided by package weight.
- If the selected farm has an active season and recorded fertilizer budget, the API calculates the remaining amount after one package. This is arithmetic only; it does not imply that buying a package is appropriate.
- The displayed compatibility note paraphrases the supplier's listed application/crop claims. Missing tomato-specific evidence is stated as such. Crop stage and farm soil data are not used to rank products.
- No application dose, nutrient deficit, or fertilizer recommendation is provided. A qualified local agronomist should determine suitability and rates from soil/water analysis and the product label.

## Updating prices

Update product details in `backend/app/fertilizers.py` only after verifying the supplier's current package size, price, product page, and availability. Change `CATALOG_UPDATED` to the date checked. Keep the provenance attached to each product; use `None` rather than guessing a price or unit.

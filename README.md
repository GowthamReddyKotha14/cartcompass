# CartCompass

Type "milk" and see which nearby store actually sells it cheapest, compared by
**price per gallon**, not by sticker price.

Sticker prices mislead. At the Kroger on N Main St, Bowling Green, OH (checked
November 2026), a half gallon of store-brand 2% milk was $1.89 and a gallon was
$2.69. The half gallon looks cheaper and costs 40% more per gallon ($3.78).

**Status:** early. Building the unit-price engine and the live store client.

## Data

- Live store prices from the official [Kroger Public API](https://developer.kroger.com/)
  (non-commercial use). Keys live in `~/.cartcompass.env`, never in this repo.

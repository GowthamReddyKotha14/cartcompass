# CartCompass

Type "milk" and see which nearby store actually sells it cheapest, compared by
**price per gallon**, not by sticker price.

Sticker prices mislead. At the Kroger on N Main St, Bowling Green, OH (checked
November 2026), a half gallon of store-brand 2% milk was $1.89 and a gallon was
$2.69. The half gallon looks cheaper and costs 40% more per gallon ($3.78).

## Try it

```bash
make install
cartcompass search milk --zip 43402
```

Needs free Kroger API keys in `~/.cartcompass.env`:

```
KROGER_CLIENT_ID=...
KROGER_CLIENT_SECRET=...
```

## How it decides "cheapest"

1. **Same thing only.** "milk" excludes milk chocolate, condensed milk and dog
   treats, and store-brand 2% is never compared with organic whole milk.
2. **Per unit, not per package.** Every size is converted to price per gallon,
   pound or item.
3. **In stock.** An out-of-stock shelf never wins.
4. **Sale prices count**, and are labeled as sales.

**Status:** the live Kroger search works. Next: other stores via receipt photos,
whole-shopping-list trips, and daily price history.

## Data

- Live store prices from the official [Kroger Public API](https://developer.kroger.com/)
  (non-commercial use). Keys live in `~/.cartcompass.env`, never in this repo.

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

## Is the cheaper store worth the drive?

```bash
cartcompass plan milk eggs bread "chicken breast" --zip 43402 --max-stores 2
```

For each item it picks the ordinary kind (or what you name: `"2% milk"`,
`"organic eggs"`), prices one typical package at every store, then tries every
one- and two-store trip. Driving is charged per mile (`--per-mile`, default
$0.20) on straight-line distance x 1.3, so a store 20 cents cheaper but 10 miles
away loses, and the output says so:

```
Best trip: Kroger Bowling Green
  groceries $2.69 + driving $0.63 (3.1 mi round trip) = $3.32

Compared with:
  Kroger Waterville      $7.34  (groceries $0.20 cheaper, driving $4.22 more)
```

(Example from the test data. Home is your ZIP's center from the Census
Bureau's ZIP list, or `--home lat,lon`.)

## Walmart, ALDI and Meijer: from receipts

These chains publish no price API, so their prices come from receipts. An AI
vision model (Claude, via the Anthropic API) reads the photo and decodes each
line:

```
$ cartcompass receipt IMG_2041.jpg
IMG_2041.jpg: Walmart, 131 W Gypsy Lane Rd 43402 on 2026-11-18
  GV 2% MLK GAL 007874235187 F → Great Value 2% Reduced Fat Milk   1 gal    $2.98   $2.98/gal
  GV LG WHT EGG 18CT F 3.47 N  → Great Value Large White Eggs      18 ct    $3.47
  ✓ items add up to the subtotal ($10.45)
saved 4 prices from Walmart
```

(Example output from the test data.) The model's answer is checked, not
trusted: line prices must add up to the printed subtotal, guessed lines are
marked `?`, and sizes are never invented. Saved receipt prices from the last 30
days join `search` and `plan` for stores inside the radius. Needs
`ANTHROPIC_API_KEY` in `~/.cartcompass.env`; iPhone HEIC photos are converted
automatically on macOS.

## Is that sale real?

Every search saves that day's prices to `data/prices.sqlite` on your machine.
After 5 days of history, the best offer is judged against what that store
usually charges (median of the last 60 days): 10% or more below is a **real
deal**; a sale tag at about the usual price is flagged **not really a sale**.

```bash
cartcompass track      # record today's prices for an everyday basket
make schedule          # macOS: do that every morning automatically
```

**Status:** live Kroger search, receipt reading, price history and trip planning
work. Next: a public showcase page.

## Data

- Live store prices from the official [Kroger Public API](https://developer.kroger.com/)
  (non-commercial use). Keys live in `~/.cartcompass.env`, never in this repo.
- Other chains from your own receipt photos, read with the
  [Anthropic API](https://docs.claude.com/).
- ZIP code locations from the U.S. Census Bureau's ZCTA gazetteer (public domain).

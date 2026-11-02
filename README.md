# Loan EBITDA Add-back Checker

A loan agreement lets a borrower add certain costs back to profit to calculate a number called EBITDA. Each agreement has its own rules about which costs are allowed, and some adjustments have limits. This means the EBITDA reported by a borrower may differ from the amount allowed under the loan agreement.

This project checks a borrower's reported EBITDA against the rules in the agreement and shows where the figures came from. All data is synthetic. No real company or client data is used.

## How it is designed to work

An AI model is intended to read the two documents and extract relevant text and numbers with references to their source. It will not perform calculations. Python will verify the extracted evidence and apply the agreement's rules and limits.

If evidence is missing, invalid or unclear, the engine flags the issue. Depending on the case, it can return a range of possible results or block the calculation and request human review.

**The AI reading part has not been built or tested.** The current prototype tests the Python validation and calculation logic using prepared inputs. No claim is made about AI extraction accuracy.

## What is built

**Implemented:** The data structures, validation logic, quote verification, calculation engine (including limits, positive and negative adjustments, ranges and difference breakdowns), checks that prevent unsupported calculations, and 12 synthetic test cases in `data/fixtures/`.

**Not implemented:** AI document extraction, report generation and the command-line interface.

## Running the tests

Python 3.11 or newer. No additional packages are required.

Run all tests from the repository root:

```bash
python -m unittest discover -s tests -t .
```

Last test run: **131 tests passed.**

Run the 12 fixture cases separately:

```bash
python -m unittest tests.test_fixtures -v
```

The tests are currently the only runnable part of the project. There is no end-to-end command for checking a new pair of documents.

## Example using synthetic data

```text
Base for the limit (profit + uncapped add-backs)  10,460
Limit: 15% of the base                           1,569
Capped add-backs claimed (1,500 + 900)            2,400
Allowed under the limit                           1,569
EBITDA allowed by the agreement                  12,029
EBITDA reported by the borrower                  12,860
Difference                                          831
```

A gain of 750 from a sale is treated as a negative amount within the cap base. It therefore reduces the base and the permitted limit. This is one reason the calculation must handle positive and negative amounts carefully.

## Project structure

- `src/addback/` — calculation and validation code.
- `src/addback/engine/` — deterministic calculation logic.
- `data/fixtures/` — synthetic documents and expected results.
- `tests/` — automated tests.

The calculation engine does not call an AI model or access the internet.

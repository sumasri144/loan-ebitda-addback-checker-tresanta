# Where the made-up data came from

Every document in this folder is **invented**. There is no real borrower, no
real lender and no real loan agreement behind any of it. No client, personal or
confidential data was used at any point.

The same is true of all 12 examples in `data/fixtures/`. Those have their own
short made-up agreements and reports, and each one carries a note saying the
`extraction.json` inside it was written by hand because the AI reading layer
does not exist.

## What the wording was based on

| Part | Source | Group |
|---|---|---|
| The **kinds** of add-back used here: non-cash charges, restructuring costs, forecast cost savings, one-off gains | Thomson Reuters Practical Law, *EBITDA Adjustments in Loan Negotiations* | **Checked** in our research stage. Not re-checked while coding |
| That a shared percentage limit on restructuring and cost-saving add-backs is a real thing, and that its base can be defined so it leaves those same add-backs out | A Teradyne credit agreement filed with the SEC in 2015 | **Checked** |
| That limits and the bases they use differ between agreements, and that 20% is not a standard figure | The same research | **Checked** |

## What we invented, and why our numbers differ from the source

| Part | Value here | Why |
|---|---|---|
| Limit percentage | **15%** | On purpose not the 20% in the real filing, so nothing here copies a real contract, and so that a hard-coded "20%" would fail our own tests |
| Window for forecast savings | **12 months** | On purpose not the 18 months in the real filing, for the same reason |
| The limit base | `Capped Adjustment Base`, written out in Section 1.01 | It is spelled out in the agreement: the starting figure plus the permitted add-backs with no limit, before the limited ones. It is **not** treated as true of other agreements |
| Category list, borrower name, lender name, site names, every figure | Invented | Made-up data only |
| The sentence saying the list is complete | Invented | Lets the system make a firm "not permitted" call rather than only "cannot tell" |
| The Schedule 3 sign rule | Invented | The format has to use `SIGNED_EXPLICIT`, and any other format is sent for manual sorting instead of being converted |

## The main example, worked by hand

```
Consolidated Net Income                                       4,200
Permitted add-backs with no limit, clauses (a)-(d) and (g):
  1,850 + 1,120 + 3,400 + 640 - 750                         = 6,260
Capped Adjustment Base                                       10,460
Limit = 15% of 10,460                                         1,569
Limited group claimed, clauses (e) + (f): 1,500 + 900         2,400
Allowed = the smaller of 2,400 and 1,569                      1,569
Cut                                                             831
EBITDA the loan allows = 10,460 + 1,569                      12,029
EBITDA the borrower reported                                 12,860
Difference, all of it caused by the limit                        831
```

Note that the 750 under clause (g) is a **minus** amount, so it lowers the
Capped Adjustment Base and therefore lowers the limit as well. If it had been
left outside the base, the limit would have been 1,681.50 and the cut 718.50.
This is one of the reasons the sign on every line matters.

## What this data does not cover

- One agreement, one period, no amendments.
- Plain text, already tidy. Real reports arrive as PDFs and spreadsheets with
  merged cells and footnotes. None of that is tested here.
- We wrote the documents, the expected answers and the categories ourselves. So
  the tests show that the **engine and the checks** are right. They are not
  evidence that AI reading would work on a real agreement.
- No conditions (the 12-month window, the non-cash rule) are used in the 12
  fixtures. Those are only covered by the unit tests.

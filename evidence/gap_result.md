# Opening gap (the information GIFT Nifty foretells): result (25 Oct 2026)

**Protocol:** `gap_protocol.md`, SHA-256 `29ee920ede88b2968eb32ea8c167de964a1f9f9cad01aa7221edd1e86cc9dd85`, registered at 17:26 before the run.
**Code:** `nfce_engine/tools/gap_study.py`.
**Data:** NIFTY daily 2016–26; the stock 3m trades (210 F&O stocks, current costs).

## Train: all FAIL (Bonferroni, p < 0.0167 needed)
| Test | Sample | Win % | Gross | **Net** | p | 95% CI | Total |
|---|---|---|---|---|---|---|---|
| **G1, follow the gap** (NIFTY, \|gap\| ≥ 0.3%, open → close) | 755 days, 2019–24 | 44.1 | −0.060%/day | **−0.140%/day** | 0.9998 | −0.209..−0.080% | −105.6% |
| G1, fade the gap (reported only) | 755 days | 45.2 | +0.060%/day | −0.020%/day | 0.697 | −0.080..+0.049% | −15.2% |
| **G2-V0**: stock signals only in the gap's direction | 5,083 of 16,598 trades, 2022–24 | 51.2 | | **−0.257R** (all −0.270R) | 1.000 | −0.298..−0.214 | |
| **G2-K4**: same, with 4× stops | 5,083 trades | 47.8 | | **−0.017R** (all −0.034R) | 1.000 | −0.056..+0.021 | |

## What it means
1. **Big gaps tend to partly reverse during the day** (fading had +0.06% gross), but the futures costs (0.08% round trip) take more than that. Following the gap loses clearly.
2. **As a filter for the stock signals,** the gap direction helps a little (−0.034 → −0.017R with K4 exits), but not into profit; the interval includes 0.
3. **GIFT Nifty therefore cannot add usable information to this system:**
   - its main value is an earlier read of the gap;
   - the gap itself does not carry an edge after costs;
   - the engine acts only from 09:30, when the gap is known exactly.
   - **GIFT Nifty is not added.**

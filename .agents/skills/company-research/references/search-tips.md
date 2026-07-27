# Search tips (from research-process-builder validation)

Learned from testing 220+ search patterns against 11 companies (SpaceX, Cohere, Harvey AI, Cursor, Clay, Lovable, Keep, Cluely, ClickUp, LeadGrow, The Kiln), ranging from $400B+ enterprises to bootstrapped micro startups. Apply these when running any process in this skill, or when improvising a search not covered by one.

- **`site:reddit.com` is completely broken** — zero results universally. use `[name] reddit discussion` without the site: operator.
- **year modifiers are the highest-leverage search modifier.** `[name] review 2026` outperforms `[name] review` by a wide margin.
- **zoominfo + linkedin are the only platforms that cover ALL company sizes**, including 6-month-old startups.
- **generic company names (Clay, Keep, Cursor, Harvey) need mandatory disambiguation.** add category qualifier or use domain.
- **kill lists save more time than pattern lists.** knowing which searches to NOT run prevents wasting 30-40% of your search budget.
- **ATS board searches are gold for hiring data.** `site:boards.greenhouse.io [name]` and `site:jobs.ashbyhq.com [name]` return actual role listings with titles and descriptions.
- **`[name] social media twitter youtube` is a trap.** returns product feature content, not the company's actual social accounts. use `site:twitter.com OR site:x.com` with company name instead.
- **OR operators in a single query are powerful.** `[name] alternatives OR competitors OR "vs"` catches 3 result types in one search.
- **wellfound (formerly angellist) is the T3 lifeline for hiring data.** small startups without greenhouse/lever/ashby pages still have wellfound profiles with employee count, funding, and industry tags.
- **`site:[domain]` with OR operators is the most efficient growth signal detector.** e.g. `site:[domain] blog OR pricing OR newsletter OR demo` catches 4+ signal types in one search.
- **rocketreach is at `rocketreach.co`, NOT `.com`.** `site:rocketreach.com` returns zero results universally. `site:rocketreach.co` returns rich org chart data including employee titles, department breakdown, and key people even for small companies.
- **combined platform OR queries are a cheat code.** `site:zoominfo.com OR site:rocketreach.co OR site:crunchbase.com [name]` pulls from 3 ungated platforms in one search.
- **churn-signal searches are a trap.** `[name] "switched from" OR "left" OR "cancelled"` returns marketing content about people switching TO the tool, not FROM it.
- **"do not recommend" and "waste of money" searches return nothing.** people don't use these exact phrases in searchable contexts. use `[name] complaints OR problems` instead.
- **never hardcode the year in process files.** use `{{current_year}}` as an input variable so processes stay valid across years.
- **ATS-specific JD searches are the best path to full job descriptions.** `site:jobs.ashbyhq.com/[company] [role]` returns exact JD links. combined ATS OR query catches roles across greenhouse/ashby/lever in one search.
- **`site:linkedin.com/jobs` is broken for web search.** returns generic LinkedIn job search pages, not company-specific listings. fetch `linkedin.com/company/[slug]/jobs/` directly instead.
- **companion processes unlock depth.** find-hiring gives breadth (all open roles), find-job-role-insights gives depth (what a specific JD reveals about strategy, tech stack, pain points). chain them for the full picture.
- **`site:{{domain}}/blog` beats `[name] blog` for finding owned content.** the former returns third-party coverage; the latter returns the company's own posts.
- **`[name] [category] newsletter` is a trap.** returns product feature content about newsletters, not the company's actual newsletter. use `site:[domain] "subscribe" OR "newsletter"` instead.
- **community platforms (discord/slack) are the most underrated growth signal.** an active community signals product-market fit and organic advocacy.
- **`site:youtube.com [name]` returns zero results.** YouTube is not searchable via `site:` operator. avoid entirely.

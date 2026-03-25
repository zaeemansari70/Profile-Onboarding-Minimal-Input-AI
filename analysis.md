# Analysis Of The Work

## Time Spent

- Around 40 minutes on thinking through the problem, deciding the scope, and planning the solution.
- Around 1 hour 30 minutes on implementation, testing, fixing issues, and improving the UI.
- 1 hour documenting.
- Total time: about 3 hours 10 minutes.

## What I Automated

The prototype automates customer onboarding from very little input:

- company name
- one or more official domains

From that input, it automatically:

- checks `robots.txt`
- checks `sitemap.xml`
- picks a small number of useful pages to crawl
- crawls pages one by one
- extracts:
  - related or likely official domains
  - brand assets like favicon, `og:image`, and likely logo images
  - business keywords
  - key people
  - social profile links
- uses the LLM to clean and structure the extracted signals into the final onboarding profile
- stores each completed onboarding profile in a local vector database
- shows the result in a simple web interface

## What I Assumed

- The customer provides at least one correct official domain.
- A small crawl is enough to get useful onboarding signals.
- I did not build impersonation detection itself because the task was focused on the onboarding stage.
- Important information is most likely to be on pages like:
  - homepage
  - about/company
  - team/leadership
  - contact
  - press/investor
- OpenAI should only help clean and organize the extracted results, not discover facts from scratch.


## Trade-Offs I Made

- I kept crawling small and sequential.
  - This keeps the flow simple and predictable.
  - It also means some deeper pages may be missed.

- I used simple rule-based extraction together with Crawl4AI.
  - This keeps the system easier to understand.
  - It also means extraction quality depends on page structure and limited crawl depth.

- I added a `requests` fallback next to Crawl4AI.
  - This helps the prototype keep working if Crawl4AI has local setup issues.
  - It is not as strong as full browser-based crawling.

- I used the LLM only for structuring the extracted profile.
  - This improves readability and consistency.
  - It also keeps the main evidence collection step deterministic.

- I stored profiles in a local vector database.
  - This makes future retrieval and comparison possible.
  - It is good for a prototype, but not enough on its own for production scale.

- I kept the frontend simple.
  - The goal was to make the results easy to read and demo.

- Crawling is synchronous.
  - This is simpler for the prototype.
  - With more time I would make it async.

## My Analysis Of The Implementation

- The main strength of the prototype is clarity.
  - The flow is easy to follow from input to result.
  - Each file has a clear job.

- Another strength is that the core extraction is deterministic.
  - That makes it easier to explain where the results came from.

- The main weakness is coverage.
  - Some websites hide useful information behind JavaScript, consent screens, or deeper navigation.

- Overall, the prototype works well for a first onboarding step.
  - It is simple, readable, and end-to-end working.

## What I Would Improve With More Time

With more time, I would extend this onboarding prototype into a stronger impersonation detection system.

- Implement async crawler

- Deeper scraping
  - scrape more pages from the official site
  - scrape Wikipedia as well
  - improve extraction of key people

- Domain similarity scoring
  - use Levenshtein distance and other typo-based checks
  - catch lookalike domains, swapped letters, extra words, and misleading TLD changes

- Content similarity scoring
  - compare suspicious pages against the official profile
  - use DOM tree comparison
  - also test screenshot-based comparison with a vision transformer

- Logo similarity scoring
  - use a vision model to compare logos and brand images
  - detect copied or very similar branding

- SSL and infrastructure mismatch checks
  - inspect SSL issuer and certificate details
  - compare company names and infrastructure signals through external APIs

- Writing style similarity
  - use an LLM to compare tone, wording, and page style between official and suspicious sites

- AI-generated website checks
  - test whether a suspicious site looks AI-generated
  - use Hugging Face AI detectors or similar models

- WHOIS and enrichment checks
  - use WHOIS lookup and webhook-based enrichment
  - compare the registration and ownership data with the trusted profile we already have

- Automatic alerts
  - if a suspicious domain looks like a real impersonation risk, send an automatic alert to the actual trusted profile or security contact

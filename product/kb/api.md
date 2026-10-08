# API and rate limits

The REST API is available on Team and Enterprise plans. Create a personal access token under Profile > Developer > Tokens. Tokens are shown once at creation; store them securely. Revoke a token from the same page.

Rate limits are 100 requests per minute per token on Team and 600 requests per minute per token on Enterprise. When you exceed the limit the API returns HTTP 429 with a Retry-After header in seconds.

Webhooks can be configured per project and deliver events for task created, task updated, task completed, and comment added. Failed webhook deliveries are retried 5 times with exponential backoff over about 2 hours, then the webhook is disabled and the project owner is emailed.

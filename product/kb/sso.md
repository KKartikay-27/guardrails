# Single sign-on (SSO)

SAML SSO is available on the Enterprise plan. Supported identity providers are Okta, Microsoft Entra ID, Google Workspace, and OneLogin.

To configure SSO, a workspace owner opens Settings > Security > SSO, copies the ACS URL and Entity ID into the identity provider, then uploads the provider's metadata XML. Test the connection before enforcing SSO. Once SSO is enforced, members can no longer sign in with a password; owners keep a password fallback in case the identity provider is down.

SCIM user provisioning is available for Okta and Entra ID. SCIM tokens expire after 365 days and must be regenerated under Settings > Security > SCIM.

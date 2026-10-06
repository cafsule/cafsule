# Production storage and HTTPS requirements

## Uploaded files

The application currently stores uploads with Django's filesystem storage. `PharmacyBrandImage.image` writes pharmacy brand images to `pharmacy/brands/<year>/<month>/<day>/`; its image type choices include exterior and interior images. `PharmacyVerificationDocument.document` writes verification documents to `pharmacy/verification/<year>/<month>/<day>/`. There are no user/profile image or prescription upload fields in the current models.

For local development, `MEDIA_ROOT=media` resolves to the repository's `media/` directory. The existing brand images and verification documents have been copied there without removing the original files, preserving their relative stored names.

Production must set `MEDIA_ROOT` to a mounted path on storage durable across container replacement and host restart. Set an absolute path outside the application directory and mount it before starting Django; production startup rejects relative paths, application-directory paths, and missing directories. Django cannot establish whether the underlying filesystem is durable, so verify the selected mount and its backups on the production host. The Compose bind mount is for local development and is not evidence of production durability. Back up this filesystem together with the database because database rows refer to paths in it. The current project has no object-storage backend.

Production startup also rejects common placeholder values for `SECRET_KEY`, `JWT_SIGNING_KEY`, and required SMTP settings. Keep actual production values in the deployment secret manager/environment, not `.env.example`.

Verification documents are private application data. Do not expose the whole media directory through a public web server. Brand images may be public, but serve them only through an explicitly public path or controlled endpoint; provide verification document downloads through authorization-checked application views. Production URL routing for these files must be reviewed before enabling uploads there.

## HTTPS reverse proxy and HSTS

Production Django settings trust `X-Forwarded-Proto: https` through `SECURE_PROXY_SSL_HEADER` and redirect insecure requests. The TLS-terminating proxy must overwrite that header from the actual connection and prevent untrusted clients from reaching Django directly. Keep HSTS disabled at initial deployment (`SECURE_HSTS_SECONDS=0`) until HTTPS, redirects, and every hostname are confirmed. Then configure a short `SECURE_HSTS_SECONDS` value and increase it after validation. Enable subdomains or preload only after confirming all affected hosts support HTTPS.

## Google sign-in

`POST /api/auth/oauth/` accepts `provider: "GOOGLE"` and a signed Google `id_token`. The backend verifies its signature, issuer, expiry, and audience against `GOOGLE_CLIENT_ID`, then uses the verified claims. Facebook and Apple are disabled until equivalent server verification exists. No frontend application is present in this repository, so its request contract cannot be confirmed here; the frontend must send the signed ID token, not a client-supplied user ID or email.

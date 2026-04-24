from werkzeug.middleware.dispatcher import DispatcherMiddleware

from Psparshcare import create_app   # import your factory from __init__.py

# Coupon engine is an optional embedded sub-application. In production, it should be
# present in the repo (recommended) or installed via submodule init. If it is missing,
# we still want the main portal to boot instead of crashing the whole site.
try:
    from psc_coupens.psc_coupens_app import create_app as create_coupon_app
except Exception as _coupon_import_error:  # pragma: no cover
    create_coupon_app = None

# Create the Flask apps using their own factories and databases.
main_app = create_app()

if create_coupon_app is not None:
    coupon_app = create_coupon_app()
else:  # pragma: no cover
    from flask import Flask

    coupon_app = Flask("psc_coupon_unavailable")

    def _unavailable_response():
        # Keep this plain-text so it is easy to see in production if misconfigured.
        return (
            "External coupon system is not available on this deployment. "
            "Ask admin to install the coupon module (psc_coupens) and redeploy.",
            503,
        )

    @coupon_app.get("/")
    def _coupon_unavailable_root():
        return _unavailable_response()

    # Keep common entry points from returning 404 so the PSC buttons don't feel broken.
    @coupon_app.get("/admin")
    @coupon_app.get("/admin/login")
    @coupon_app.get("/coupon/entry")
    def _coupon_unavailable_common():
        return _unavailable_response()

# Expose the coupon engine as a dedicated sub-application inside PSC.
app = DispatcherMiddleware(
    main_app,
    {
        "/external-coupen-system": coupon_app,
    },
)

if __name__ == "__main__":
    # Run in debug mode for development
    from werkzeug.serving import run_simple

    run_simple("127.0.0.1", 5000, app, use_debugger=True, use_reloader=True)

from werkzeug.middleware.dispatcher import DispatcherMiddleware

from Psparshcare import create_app   # import your factory from __init__.py
from psc_coupens.psc_coupens_app import create_app as create_coupon_app

# Create the Flask apps using their own factories and databases.
main_app = create_app()
coupon_app = create_coupon_app()

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

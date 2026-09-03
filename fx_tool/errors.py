"""Every failure the endpoint can report, as a machine code plus a human sentence."""

from __future__ import annotations


class ConversionError(Exception):
    """Raised anywhere in the request path; the app turns it into the error JSON."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def invalid_amount(message: str) -> ConversionError:
    return ConversionError(400, "invalid_amount", message)


def invalid_currency(value: str) -> ConversionError:
    return ConversionError(400, "invalid_currency", f"'{value}' is not a three-letter ISO 4217 currency code.")


def same_currency(code: str) -> ConversionError:
    return ConversionError(400, "same_currency", f"'from' and 'to' are both {code}; there is nothing to convert.")


def invalid_date(value: str) -> ConversionError:
    return ConversionError(400, "invalid_date", f"'{value}' is not a date in YYYY-MM-DD form.")


def date_in_future(asked: str, today: str) -> ConversionError:
    return ConversionError(
        400, "date_in_future", f"No rate exists yet for {asked}; the latest possible date is {today}."
    )


def date_before_series(asked: str, first: str) -> ConversionError:
    return ConversionError(
        400, "date_before_series", f"ECB reference rates start on {first}; {asked} is before that."
    )


def unknown_currency(base: str, target: str) -> ConversionError:
    return ConversionError(
        404, "unknown_currency", f"The ECB publishes no rate for {base}/{target}; one of the codes is not supported."
    )


def no_rate_for_date(asked: str, newest: str) -> ConversionError:
    return ConversionError(
        404,
        "no_rate_for_date",
        f"No rate was published for {asked} and the nearest earlier one ({newest}) is too old to stand in for it.",
    )


def upstream_unavailable(detail: str) -> ConversionError:
    return ConversionError(503, "upstream_unavailable", f"Could not reach the rate provider: {detail}.")


def upstream_timeout(seconds: float) -> ConversionError:
    return ConversionError(504, "upstream_timeout", f"The rate provider did not answer within {seconds:g} seconds.")


def upstream_error(status: int) -> ConversionError:
    return ConversionError(502, "upstream_error", f"The rate provider answered with HTTP {status}.")


def upstream_invalid(detail: str) -> ConversionError:
    return ConversionError(502, "upstream_invalid", f"The rate provider sent an answer we could not trust: {detail}.")

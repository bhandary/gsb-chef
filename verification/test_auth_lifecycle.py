"""Generated-input checks for the auth.py sign-up token lifecycle.

Hypothesis draws emails, passwords, and sequences of signup, reissue, and
verify. The same probes are run against source variants of auth.py that
delete or reorder a guard; those variants must fail.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
from datetime import timedelta
from pathlib import Path

import pytest
from hypothesis import HealthCheck, Phase, example, given, settings, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

import auth
from verification.lifecycle import (
    ISSUED_AT,
    add_user,
    assert_storage,
    capture_signup,
    expect_verify,
    fresh_database,
    stored_expiry,
    user_id,
)
from verification.probes import CHECKS

ROOT = Path(__file__).resolve().parents[1]
AUTH_PATH = ROOT / "auth.py"

EMAILS = st.from_regex(r"[a-z0-9]{1,12}@[a-z0-9]{1,12}\.[a-z]{2,4}", fullmatch=True)
PASSWORDS = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=8,
    max_size=40,
)
CHECK_SETTINGS = settings(
    max_examples=30,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow],
)


class _Issued:
    def __init__(self, raw: str, email: str, expires_at: datetime):
        self.raw = raw
        self.email = email
        self.expires_at = expires_at
        self.present = True
        self.used = False


def _record_issue(conn, raw: str, email: str, tokens: list[_Issued]) -> None:
    for item in tokens:
        if item.email == email and item.present and not item.used:
            item.present = False
    tokens.append(_Issued(raw, email, stored_expiry(conn, raw)))


def _outcome(token: _Issued, when: datetime) -> str:
    if not token.present:
        return "invalid"
    if token.used:
        return "used"
    if when >= token.expires_at:
        return "expired"
    return "ok"


class TokenLifecycle(RuleBasedStateMachine):
    """Sequences of auth.signup, issue_verification_token, and verify_email_token."""

    def __init__(self):
        super().__init__()
        self._database = tempfile.TemporaryDirectory()
        self._previous_env = {
            key: os.environ.get(key)
            for key in (
                "GSB_AUTH_DB",
                "SMTP_HOST",
                "APP_BASE_URL",
                "GSB_VERIFICATION_TTL_SECONDS",
            )
        }
        os.environ["GSB_AUTH_DB"] = str(Path(self._database.name) / "auth.db")
        os.environ["SMTP_HOST"] = ""
        os.environ["APP_BASE_URL"] = "http://localhost:3000"
        os.environ.pop("GSB_VERIFICATION_TTL_SECONDS", None)
        self.passwords: dict[str, str] = {}
        self.verified: set[str] = set()
        self.tokens: list[_Issued] = []
        self.raw_secrets: set[str] = set()

    def teardown(self):
        self._database.cleanup()
        for key, value in self._previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    @invariant()
    def storage_matches_hash_functions(self):
        if not Path(os.environ["GSB_AUTH_DB"]).exists():
            return
        conn = auth.connect()
        try:
            assert_storage(conn, self.passwords, self.raw_secrets)
        finally:
            conn.close()

    @rule(email=EMAILS, password=PASSWORDS)
    def signup(self, email: str, password: str):
        if email not in self.passwords:
            raw = capture_signup(email, password)
            self.passwords[email] = password
            self.raw_secrets.add(raw)
            conn = auth.connect()
            try:
                _record_issue(conn, raw, email, self.tokens)
            finally:
                conn.close()
            return
        try:
            raw = capture_signup(email, password)
        except auth.AuthError as exc:
            if email in self.verified:
                assert exc.code == "exists", exc.code
            else:
                assert exc.code == "invalid", exc.code
                assert password != self.passwords[email]
            return
        assert email not in self.verified
        assert password == self.passwords[email]
        self.raw_secrets.add(raw)
        conn = auth.connect()
        try:
            _record_issue(conn, raw, email, self.tokens)
        finally:
            conn.close()

    @rule(
        which=st.integers(min_value=0, max_value=6),
        ttl_seconds=st.integers(min_value=1, max_value=5_000),
        shift_seconds=st.integers(min_value=0, max_value=5_000),
    )
    def reissue(self, which: int, ttl_seconds: int, shift_seconds: int):
        if not self.passwords:
            return
        email = sorted(self.passwords)[which % len(self.passwords)]
        moment = ISSUED_AT + timedelta(seconds=shift_seconds)
        conn = auth.connect()
        try:
            raw = auth.issue_verification_token(
                conn,
                user_id(conn, email),
                now=moment,
                ttl=timedelta(seconds=ttl_seconds),
            )
            self.raw_secrets.add(raw)
            _record_issue(conn, raw, email, self.tokens)
        finally:
            conn.close()

    @rule(
        which=st.integers(min_value=0, max_value=8),
        offset_seconds=st.integers(min_value=-10_000, max_value=10_000),
    )
    def verify(self, which: int, offset_seconds: int):
        if not self.tokens:
            return
        token = self.tokens[which % len(self.tokens)]
        when = token.expires_at + timedelta(seconds=offset_seconds)
        outcome = _outcome(token, when)
        session = expect_verify(
            token.raw,
            when,
            outcome,
            email=token.email,
            passwords=self.passwords,
            raw_secrets=self.raw_secrets,
        )
        if outcome == "ok":
            token.used = True
            self.verified.add(token.email)
            assert session is not None
            expect_verify(
                token.raw,
                when,
                "used",
                email=token.email,
                passwords=self.passwords,
                raw_secrets=self.raw_secrets,
            )


TestTokenLifecycle = TokenLifecycle.TestCase
TestTokenLifecycle.settings = settings(
    max_examples=20,
    stateful_step_count=8,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow],
    # Shrinking a stateful failure reruns Argon2id for minutes. The explicit
    # examples on the single-token test are the minimal counterexamples.
    phases=[Phase.explicit, Phase.reuse, Phase.generate],
)


@CHECK_SETTINGS
@given(
    email=EMAILS,
    password=PASSWORDS,
    ttl_seconds=st.integers(min_value=1, max_value=10_000),
    offset_seconds=st.integers(min_value=-10_000, max_value=10_000),
)
@example(email="cook@example.com", password="pantry-secret", ttl_seconds=60, offset_seconds=0)
@example(email="cook@example.com", password="pantry-secret", ttl_seconds=60, offset_seconds=-1)
def test_token_verifies_one_account_once_before_expiry(
    email: str, password: str, ttl_seconds: int, offset_seconds: int
):
    bystander = "bystander@example.com"
    if email == bystander:
        bystander = "other@example.com"
    bystander_password = "bystander-pass"
    with fresh_database():
        passwords = {email: password, bystander: bystander_password}
        add_user(bystander, bystander_password)
        add_user(email, password)
        conn = auth.connect()
        try:
            raw = auth.issue_verification_token(
                conn,
                user_id(conn, email),
                now=ISSUED_AT,
                ttl=timedelta(seconds=ttl_seconds),
            )
            expires_at = stored_expiry(conn, raw)
        finally:
            conn.close()
        secrets = {raw}
        when = expires_at + timedelta(seconds=offset_seconds)
        outcome = "expired" if when >= expires_at else "ok"
        expect_verify(
            raw, when, outcome, email=email, passwords=passwords, raw_secrets=secrets
        )
        if outcome == "ok":
            expect_verify(
                raw, when, "used", email=email, passwords=passwords, raw_secrets=secrets
            )
            later = expires_at + timedelta(seconds=1)
            expect_verify(
                raw, later, "used", email=email, passwords=passwords, raw_secrets=secrets
            )


@CHECK_SETTINGS
@given(email=EMAILS, password=PASSWORDS, other_password=PASSWORDS)
def test_replaced_unused_token_is_invalid(email, password, other_password):
    with fresh_database():
        first = capture_signup(email, password)
        passwords = {email: password}
        secrets = {first}
        conn = auth.connect()
        try:
            assert_storage(conn, passwords, secrets)
            second = auth.issue_verification_token(
                conn,
                user_id(conn, email),
                now=ISSUED_AT,
                ttl=timedelta(hours=2),
            )
            secrets.add(second)
            assert_storage(conn, passwords, secrets)
        finally:
            conn.close()
        expect_verify(
            first,
            ISSUED_AT,
            "invalid",
            email=email,
            passwords=passwords,
            raw_secrets=secrets,
        )
        expect_verify(
            second,
            ISSUED_AT,
            "ok",
            email=email,
            passwords=passwords,
            raw_secrets=secrets,
        )
        if other_password != password:
            with pytest.raises(auth.AuthError) as exc:
                auth.signup(email, other_password)
            assert exc.value.code == "exists"


def test_two_threads_consume_a_token_once():
    import threading

    with fresh_database():
        email = "cook@example.com"
        password = "pantry-secret"
        add_user(email, password)
        conn = auth.connect()
        try:
            raw = auth.issue_verification_token(
                conn, user_id(conn, email), now=ISSUED_AT, ttl=timedelta(hours=1)
            )
        finally:
            conn.close()
        barrier = threading.Barrier(2)
        results: list[tuple] = []

        def worker():
            barrier.wait()
            try:
                result = auth.verify_email_token(raw, now=ISSUED_AT)
                results.append(("ok", result["email"]))
            except auth.AuthError as exc:
                results.append(("err", exc.code))
            except Exception as exc:
                results.append(("exc", type(exc).__name__, str(exc)))

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        oks = [item for item in results if item[0] == "ok"]
        errs = [item for item in results if item[0] == "err"]
        unexpected = [item for item in results if item[0] == "exc"]
        assert unexpected == [], unexpected
        assert len(oks) == 1 and oks[0][1] == email, results
        assert errs == [("err", "used")], results


# Each variant is a copy of auth.py with one guard removed or reordered.
# The named probe must print BROKEN. The same probe prints HOLDS on auth.py.
MUTANTS = {
    "drop-used-guards": {
        "probe": "once",
        "property": "P2 a used token is rejected",
        "replacements": [
            (
                '        if row["used_at"] is not None:\n'
                '            raise AuthError("used", "This verification link has already been used.")\n',
                "",
            ),
            (
                "WHERE id = ? AND used_at IS NULL AND expires_at > ?",
                "WHERE id = ? AND expires_at > ?",
            ),
        ],
    },
    "drop-expiry-guards": {
        "probe": "expiry",
        "property": "P3 a token is rejected at expires_at",
        "replacements": [
            (
                "        if expires_at <= current:\n"
                '            raise AuthError("expired", "This verification link has expired.")\n',
                "",
            ),
            (
                "            WHERE id = ? AND used_at IS NULL AND expires_at > ?\n"
                '            """,\n'
                "            (_iso(current), row[\"id\"], _iso(current)),\n",
                "            WHERE id = ? AND used_at IS NULL\n"
                '            """,\n'
                "            (_iso(current), row[\"id\"]),\n",
            ),
        ],
    },
    "verify-before-expiry-check": {
        "probe": "rejected_is_noop",
        "property": "P3 an expired verify does not mark the account verified",
        "replacements": [
            (
                "        if expires_at <= current:\n",
                "        conn.execute(\n"
                '            "UPDATE users SET email_verified_at = ? WHERE id = ?",\n'
                "            (_iso(current), row[\"user_id\"]),\n"
                "        )\n"
                "        conn.commit()\n"
                "        if expires_at <= current:\n",
            ),
        ],
    },
    "verify-every-account": {
        "probe": "one_account",
        "property": "P1 a token verifies only its own account",
        "replacements": [
            (
                '            "UPDATE users SET email_verified_at = ? WHERE id = ?",\n'
                "            (_iso(current), row[\"user_id\"]),\n",
                '            "UPDATE users SET email_verified_at = ?",\n'
                "            (_iso(current),),\n",
            ),
        ],
    },
    "store-raw-token": {
        "probe": "stored_token",
        "property": "P4 the stored token is hash_token(token)",
        "replacements": [
            (
                "(user_id, hash_token(token), _iso(expires_at), _iso(current)),",
                "(user_id, token, _iso(expires_at), _iso(current)),",
            ),
        ],
    },
    "store-raw-password": {
        "probe": "password_hash",
        "property": "P5 signup stores hash_password(password)",
        "replacements": [
            (
                "(cleaned, hash_password(password), now),",
                "(cleaned, password, now),",
            ),
        ],
    },
}


def _mutate(source: str, replacements: list[tuple[str, str]]) -> str:
    mutated = source
    for old, new in replacements:
        count = mutated.count(old)
        if count != 1:
            raise AssertionError(
                f"variant pattern appeared {count} times, expected 1:\n"
                f"{textwrap.shorten(old, width=120)}"
            )
        mutated = mutated.replace(old, new, 1)
    if mutated == source:
        raise AssertionError("variant did not change auth.py")
    return mutated


def _run_probe(probe: str, auth_source: str | None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("GSB_AUTH_DB", None)
    # python -m puts the working directory first on sys.path. A variant has to
    # be that directory, or the import loads the real auth.py and the probe holds.
    with tempfile.TemporaryDirectory() as directory:
        if auth_source is not None:
            Path(directory, "auth.py").write_text(auth_source)
            env["PYTHONPATH"] = str(ROOT)
            cwd = directory
        else:
            env["PYTHONPATH"] = str(ROOT)
            cwd = str(ROOT)
        return subprocess.run(
            [sys.executable, "-m", "verification.probes", probe],
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )


@pytest.mark.parametrize("name", sorted(CHECKS))
def test_probe_holds_on_auth_py(name: str):
    result = _run_probe(name, None)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "HOLDS" in result.stdout


@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_broken_variant_fails_its_property(name: str):
    spec = MUTANTS[name]
    source = _mutate(AUTH_PATH.read_text(), spec["replacements"])
    result = _run_probe(spec["probe"], source)
    assert result.returncode == 1, (
        f"{name} did not break {spec['property']}\n"
        f"{result.stdout}\n{result.stderr}"
    )
    assert result.stdout.startswith("BROKEN:"), result.stdout

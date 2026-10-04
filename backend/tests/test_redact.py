from collections import Counter

from aion.ai.redact import redact_pack, redact_text


def test_log_profile_masks_pii_and_secrets():
    c = Counter()
    out = redact_text("payment failed for priya.sharma@example.com phone +91 9876543210 card 4111 1111 1111 1111 "
                      "password=hunter2xyz Authorization: Bearer abcdefghijklmnop123", "log", c)
    for leaked in ("priya.sharma@example.com", "9876543210", "4111 1111 1111 1111", "hunter2xyz", "abcdefghijklmnop123"):
        assert leaked not in out
    assert "password=[REDACTED:secret]" in out
    assert c["email"] == 1 and c["card_number"] == 1 and c["phone"] == 1


def test_known_key_formats_are_masked_everywhere():
    for key in ("AKIAIOSFODNN7EXAMPLE", "ghp_" + "a" * 36, "sk-ant-api03-" + "x" * 30,
                "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N"):
        assert key not in redact_text(f"token used: {key}", "code")


def test_values_that_look_numeric_but_are_not_sensitive_survive():
    text = "commit 69cfda3e4f1c2b7a8d9e0f1a2b3c4d5e6f7a8b9c failed at app/pricing.py:17 for order 1002, total 18878.82"
    assert redact_text(text, "log") == text
    assert redact_text("card 1234 5678 9012 3456", "log") == "card 1234 5678 9012 3456"  # fails Luhn: not a card


def test_code_profile_keeps_code_quotable():
    code = 'def login(password):\n    token = make_token(user_email)\n    return password == "x"\n'
    assert redact_text(code, "code") == code


def test_pack_redaction_counts_and_keeps_shas():
    pack = {"analysed_revision": "a" * 40,
            "incident": {"title": "ValueError: bad email bob@corp.example"},
            "evidence": [{"id": "TRACE-1", "kind": "stack_trace", "stack_trace": "user=bob@corp.example",
                          "sample_failing_requests": [{"query": "email=bob@corp.example&password=hunter2x"}]},
                         {"id": "COMMIT-1", "kind": "commit", "diff": "+ADMIN = 'bob@corp.example'\n"}]}
    red, counts = redact_pack(pack)
    assert red["analysed_revision"] == "a" * 40
    assert "bob@corp.example" not in str(red["incident"]) + str(red["evidence"][0])
    assert "bob@corp.example" in red["evidence"][1]["diff"]  # code profile: e-mails in code are left alone
    assert counts["email"] == 3 and counts["secret_value"] == 1
    assert "bob@corp.example" in pack["incident"]["title"]  # original untouched

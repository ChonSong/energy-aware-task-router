"""Tests for the in-memory rate limiter."""

from __future__ import annotations

import time
import uuid

import pytest

from energy_router.ratelimit import RateLimiter, extract_client_key


class TestRateLimiterCore:
    def test_allows_first_request(self):
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        assert limiter.check("client-1") is True

    def test_allows_within_limit(self):
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        for _ in range(5):
            assert limiter.check("client-1") is True

    def test_blocks_over_limit(self):
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        for _ in range(3):
            limiter.check("client-1")
        assert limiter.check("client-1") is False

    def test_separate_keys_independent(self):
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        assert limiter.check("alice") is True
        assert limiter.check("alice") is True
        assert limiter.check("alice") is False  # alice capped
        assert limiter.check("bob") is True  # bob still allowed

    def test_burst_limit(self):
        limiter = RateLimiter(
            max_requests=100, window_seconds=60,
            burst_max=2, burst_window_seconds=1,
        )
        assert limiter.check("burst-client") is True
        assert limiter.check("burst-client") is True
        assert limiter.check("burst-client") is False  # burst cap hit

    def test_reset_single_key(self):
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        limiter.check("x")
        limiter.check("x")
        assert limiter.check("x") is False
        limiter.reset("x")
        assert limiter.check("x") is True  # reset clears

    def test_reset_all_keys(self):
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        limiter.check("a")
        limiter.check("b")
        assert limiter.check("a") is False
        assert limiter.check("b") is False
        limiter.reset()
        assert limiter.check("a") is True
        assert limiter.check("b") is True

    def test_remaining_counts_down(self):
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        assert limiter.remaining("test") == 5
        limiter.check("test")
        assert limiter.remaining("test") == 4
        limiter.check("test")
        assert limiter.remaining("test") == 3

    def test_window_slides_over_time(self):
        limiter = RateLimiter(max_requests=2, window_seconds=0.1)
        limiter.check("sliding")
        limiter.check("sliding")
        assert limiter.check("sliding") is False
        time.sleep(0.15)
        assert limiter.check("sliding") is True  # window slid


class TestExtractClientKey:
    def test_uses_forwarded_for(self):
        class FakeRequest:
            headers = {"x-forwarded-for": "203.0.113.5, 10.0.0.1"}
            client = None
        assert extract_client_key(FakeRequest()) == "203.0.113.5"

    def test_falls_back_to_client_host(self):
        class FakeRequest:
            headers = {}
            client = type("Client", (), {"host": "192.168.1.1"})()
        assert extract_client_key(FakeRequest()) == "192.168.1.1"

    def test_falls_back_to_uuid(self):
        class FakeRequest:
            headers = {}
            client = type("Client", (), {"host": ""})()
        key = extract_client_key(FakeRequest())
        # uuid4 is 36 chars
        assert len(key) == 36

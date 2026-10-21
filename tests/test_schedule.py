from resources.lib.schedule import Schedule, interval


def clock():
    value = [0]
    return value, lambda: value[0]


def test_expensive_snapshots_wait_fifteen_seconds_and_cloud_waits_sixty():
    current, now = clock()
    schedule = Schedule(now=now)
    assert schedule.take() == (True, True)
    for second in range(1, 60):
        current[0] = second
        assert schedule.take() == (second % 15 == 0, False)
    current[0] = 60
    assert schedule.take() == (True, True)


def test_stop_events_are_coalesced_without_postponing_the_first_request():
    current, now = clock()
    schedule = Schedule(now=now)
    schedule.take()
    current[0] = 5
    schedule.request(delay=2)
    current[0] = 6
    schedule.request(delay=2)
    assert schedule.take() == (False, False)
    current[0] = 7
    assert schedule.take() == (True, True)
    assert schedule.take() == (False, False)


def test_manual_request_runs_without_waiting_for_the_periodic_timer():
    current, now = clock()
    schedule = Schedule(now=now)
    schedule.take()
    current[0] = 1
    schedule.request()
    assert schedule.take() == (True, True)


def test_network_backoff_does_not_disable_local_checkpoints():
    current, now = clock()
    schedule = Schedule(now=now)
    schedule.take()
    assert schedule.failure() == 120
    current[0] = 15
    assert schedule.take() == (True, False)
    current[0] = 120
    assert schedule.take() == (True, True)
    assert schedule.failure() == 180
    schedule.success()
    assert schedule.failure() == 120


def test_manual_request_can_retry_after_wake_during_network_backoff():
    current, now = clock()
    schedule = Schedule(now=now)
    schedule.take()
    schedule.failure()
    current[0] = 5
    schedule.request(delay=2)
    current[0] = 7
    assert schedule.take() == (True, True)


def test_interval_values_are_bounded_and_can_be_changed_at_runtime():
    assert interval("", 15, 5, 120) == 15
    assert interval("nan", 15, 5, 120) == 15
    assert interval("1", 15, 5, 120) == 5
    assert interval("999", 15, 5, 120) == 120
    current, now = clock()
    schedule = Schedule(now=now)
    schedule.take()
    current[0] = 1
    schedule.configure(5, 30)
    current[0] = 6
    assert schedule.take() == (True, False)
    current[0] = 31
    assert schedule.take() == (True, True)

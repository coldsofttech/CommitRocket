from commitrocket.eta import EtaEstimator, format_duration


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_no_estimate_before_start_or_progress():
    clock = FakeClock()
    eta = EtaEstimator(clock)
    assert eta.estimate(10, 100) is None

    eta.start()
    clock.now = 60
    assert eta.estimate(0, 100) is None


def test_no_estimate_until_enough_time_has_passed():
    clock = FakeClock()
    eta = EtaEstimator(clock)
    eta.start()
    clock.now = 2
    assert eta.estimate(10, 100) is None


def test_estimate_uses_average_speed_of_whole_run():
    clock = FakeClock()
    eta = EtaEstimator(clock)
    eta.start()
    clock.now = 10
    # 25 bytes in 10 s -> 2.5 B/s, 75 left -> 30 s
    assert eta.estimate(25, 100) == 30
    clock.now = 40
    # 50 bytes in 40 s -> 1.25 B/s, 50 left -> 40 s
    assert eta.estimate(50, 100) == 40


def test_format_duration():
    assert format_duration(3725) == "1:02:05"
    assert format_duration(-3) == "0:00:00"

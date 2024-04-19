import RPi.GPIO as GPIO
import math
import socket
import time
import logging
import multiprocessing
import configparser
import traceback
import signal
from typing import Dict, Union

# * Use Type Hints
RPiPinType = int
GPIOValueType = bool
RotationType = float
CounterType = int

# * Read config file
config = configparser.ConfigParser()
config_file_path = "astro-project/forPi/config.ini"

try:
    config.read(config_file_path)
except FileNotFoundError:
    logging.error(f"Configuration file not found: {config_file_path}")
    exit(1)
except Exception as e:
    logging.error(f"Error reading configuration file: {e}")
    exit(1)

# * Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("observatory.log"),
        logging.StreamHandler(),
    ],
)


# * Graceful shutdown
def shutdown_gracefully(signum, frame):
    logging.info("Received signal to shutdown gracefully")
    # Add your cleanup logic here
    exit(0)


signal.signal(signal.SIGINT, shutdown_gracefully)
signal.signal(signal.SIGTERM, shutdown_gracefully)


# * Class for the 4 channel relay that controls the rotation and shutter motors
class Relay:
    def __init__(self) -> None:
        self.pins: Dict[str, RPiPinType] = {
            "ccw": int(config.get("Relay Settings", "ccw_pin")),
            "cw": int(config.get("Relay Settings", "cw_pin")),
            "close": int(config.get("Relay Settings", "close_pin")),
            "open": int(config.get("Relay Settings", "open_pin")),
        }

        for key, value in self.pins.items():
            GPIO.setup(value, GPIO.OUT)
            GPIO.output(value, GPIO.LOW)

        logging.info("relay created")

    def __del__(self) -> None:
        """
        Clean up GPIO resources when the Relay object is destroyed.
        """
        GPIO.cleanup()


# * Class for the rotary encoder that will measure rotation of the observatory dome
class Encoder:
    def __init__(self, dome_diameter: int) -> None:
        self.dome_diameter: int = dome_diameter

        self.pins: Dict[str, RPiPinType] = {
            "clk": int(config.get("Encoder Settings", "clk_pin")),
            "dt": int(config.get("Encoder Settings", "dt_pin")),
        }

        for key, value in self.pins.items():
            GPIO.setup(value, GPIO.IN)

        self.is_measuring: multiprocessing.Value = multiprocessing.Value(
            "i", 0
        )  # * this makes the value shared across different processes
        self.is_home: multiprocessing.Value = multiprocessing.Value(
            "i", 1
        )  # * this makes the value shared across different processes

        self.resolution: int = int(config.get("Encoder Settings", "resolution"))
        self.wheel_circumference_mm: int = int(
            config.get("Encoder Settings", "wheel_circumference_mm")
        )
        try:
            with open("dome_rotation.txt", "r") as dome_rotation:
                self.counter: multiprocessing.Value = multiprocessing.Value(
                    "i", int(dome_rotation.read().decode("utf-8"))
                )
        except Exception as e:
            logging.error(f"Error reading dome_rotation.txt: {e}")
            self.counter: multiprocessing.Value = multiprocessing.Value(
                "i",
                int(
                    int(config.get("Observatory Settings", "home_rotation"))
                    / 360
                    * (math.pi * self.dome_diameter)
                    / self.wheel_circumference_mm
                    * self.resolution
                ),
            )  # * this makes the value shared across different processes
        self.clk_last_state: multiprocessing.Value = multiprocessing.Value(
            "i", GPIO.input(self.pins["clk"])
        )  # * this makes the value shared across different processes

        logging.info("encoder created")

    def __read_from_encoder(self) -> None:
        """
        Read encoder values and update the counter value.
        """
        try:
            dome_rotation = open("dome_rotation.txt", "w")
            while self.is_measuring.value:
                time.sleep(
                    0.0005
                )  # * sleeping for performance. Speed of dome is 690 clicks / 5.2 degrees per second. So, we only need to loop encoder reading every 1.4ms. Loopoing every 0.5ms for headroom.
                clk_state: GPIOValueType = GPIO.input(self.pins["clk"])
                dt_state: GPIOValueType = GPIO.input(self.pins["dt"])

                if clk_state != self.clk_last_state.value:
                    if dt_state != clk_state:
                        self.counter.value -= 1
                    else:
                        self.counter.value += 1
                    self.clk_last_state.value = clk_state
                    dome_rotation.seek(0)
                    dome_rotation.write(str(self.counter.value))
                    dome_rotation.flush()

        except Exception as e:
            logging.error(f"exception error at encoder: {e}")
        finally:
            dome_rotation.close()

    def toggle_measure(self) -> None:
        """
        Toggle the measurement of encoder values.
        """
        self.is_measuring.value = not self.is_measuring.value

        if self.is_measuring.value:
            process = multiprocessing.Process(target=self.__read_from_encoder)
            process.start()

            logging.info("beginning reading from encoder")
        else:
            logging.info("stopped reading from encoder")

    def __del__(self) -> None:
        """
        Clean up GPIO resources when the Encoder object is destroyed.
        """
        GPIO.cleanup()


# * Class for the observatory itself where control functions are centralized
class Observatory:
    def __init__(self) -> None:
        try:
            with open("shutter_status.txt", "rb") as shutter_status:
                self.is_shutter_open: bool = bool(shutter_status.read().decode("utf-8"))
        except Exception as e:
            logging.error(f"Error reading shutter_status.txt: {e}")
            self.is_shutter_open: bool = False

        self.open_time: int = int(
            config.get("Observatory Settings", "open_time")
        )  # * in sec
        self.close_time: int = int(
            config.get("Observatory Settings", "close_time")
        )  # * in sec
        self.control_box_rotation: int = int(
            config.get("Observatory Settings", "control_box_rotation")
        )  # * in deg
        self.decel_angle: float = float(
            config.get("Observatory Settings", "decel_angle")
        )  # * in deg
        self.target_rotation: RotationType = 0.0  # * in deg
        self.sync_threshold: int = int(
            config.get("Observatory Settings", "sync_threshold")
        )  # * in deg
        self.diameter: int = int(
            config.get("Observatory Settings", "diameter_mm")
        )  # * in mm

        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        self.relay: Relay = Relay()
        self.encoder: Encoder = Encoder(self.diameter)

        self.operations: Dict[str, str] = {
            "rotate_ccw": "ccw",
            "rotate_cw": "cw",
            "close": "close",
            "open": "open",
        }
        self.statuses: Dict[str, bool] = {"start": True, "stop": False}
        self.open_logic: Dict[bool, int] = {
            True: self.close_time,
            False: self.open_time,
        }

        self.important_values: Dict[str, Union[bool, CounterType]] = {
            "shutter_state": self.is_shutter_open,
            "encoder_count": self.encoder.counter.value,
        }

        logging.info("observatory created")

    def operate(self, operation: str, status: str = None) -> None:
        """
        Operate the relay to control the rotation and shutter motors.

        Args:
            operation (str): The operation to perform (rotate_ccw, rotate_cw, close, open).
            status (str, optional): The status to set (start or stop). If not provided, the shutter will be opened/closed.
        """
        try:
            if status is not None:
                GPIO.output(
                    int(self.relay.pins[self.operations.get(operation)]),
                    self.statuses.get(status),
                )
            else:
                with open("shutter_status.txt", "w") as shutter_status:
                    GPIO.output(
                        int(self.relay.pins[self.operations.get(operation)]), GPIO.HIGH
                    )
                    if self.is_shutter_open:
                        time.sleep(self.open_logic.get(self.is_shutter_open))
                        self.is_shutter_open = not self.is_shutter_open
                        shutter_status.write(
                            str(self.is_shutter_open)
                        )  # * writes False
                    else:
                        time.sleep(self.open_logic.get(self.is_shutter_open))
                        self.is_shutter_open = not self.is_shutter_open
                        shutter_status.write(str(self.is_shutter_open))  # * writes True
                    GPIO.output(
                        int(self.relay.pins[self.operations.get(operation)]), GPIO.LOW
                    )

        except Exception as e:
            logging.error(f"exception error at operate: {e}")

    def _clicks_to_degrees(self, clicks: CounterType) -> RotationType:
        """
        Convert encoder clicks to degrees of rotation.

        Args:
            clicks (CounterType): The number of encoder clicks.

        Returns:
            RotationType: The rotation in degrees.
        """
        return (
            clicks
            / self.encoder.resolution
            * self.encoder.wheel_circumference_mm
            / (math.pi * self.dome_diameter)
            * 360
        )

    def _sync(self, dir: str, edge: bool) -> None:
        """
        Synchronize the observatory rotation with the target rotation.

        Args:
            dir (str): The direction of rotation (cw or ccw).
            edge (bool): Whether to consider the edge case for rotation.
        """
        self.operate(f"rotate_{dir}", "start")

        if not edge:
            if dir in ("cw",):
                while (
                    self._normalize_to_360(
                        self._clicks_to_degrees(self.encoder.counter.value)
                    )
                    < self.target_rotation - self.decel_angle
                ):
                    print(
                        f"Shutter rotation: {self._normalize_to_360(self._clicks_to_degrees(self.encoder.counter.value))}"
                    )
                    print(f"Target rotation: {self.target_rotation - self.decel_angle}")
                    time.sleep(0.1)
            else:
                while (
                    self._normalize_to_360(
                        self._clicks_to_degrees(self.encoder.counter.value)
                    )
                    > self.target_rotation + self.decel_angle
                ):
                    time.sleep(0.1)
        else:
            if dir in ("cw",) and edge:
                while (
                    self._normalize_to_360(
                        self._clicks_to_degrees(self.encoder.counter.value)
                    )
                    + 180
                ) % 360 < (self.target_rotation - self.decel_angle + 180) % 360:
                    time.sleep(0.1)
            else:
                while (
                    self._normalize_to_360(
                        self._clicks_to_degrees(self.encoder.counter.value)
                    )
                    + 180
                ) % 360 > (self.target_rotation + self.decel_angle + 180) % 360:
                    time.sleep(0.1)

        self.operate(f"rotate_{dir}", "stop")

    def _normalize_to_360(self, value: RotationType) -> RotationType:
        """
        Normalize an angle value to the range [0, 360) degrees.

        Args:
            value (RotationType): The angle value to normalize.

        Returns:
            RotationType: The normalized angle value.
        """
        return (value + 360) % 360

    def check_for_sync(
        self, target_rotation_from_socket: RotationType, force_sync: bool
    ) -> None:
        """
        Check if the observatory rotation needs to be synchronized with the target rotation.

        Args:
            target_rotation_from_socket (RotationType): The target rotation received from the socket.
            force_sync (bool): Whether to force synchronization regardless of the threshold.
        """
        self.target_rotation = target_rotation_from_socket

        target: RotationType = self.target_rotation
        shutter: RotationType = self._normalize_to_360(
            self._clicks_to_degrees(self.encoder.counter.value)
        )

        if not force_sync:
            threshold: int = self.sync_threshold
        else:
            threshold: int = 0

        low_threshold: RotationType = self._normalize_to_360(target - threshold)
        high_threshold: RotationType = self._normalize_to_360(target + threshold)

        if abs(high_threshold - target) == threshold == abs(target - low_threshold):
            if not low_threshold <= shutter <= high_threshold:
                if shutter > high_threshold:
                    self._sync("ccw", False)
                else:
                    self._sync("cw", False)
        else:
            low_threshold_moved: RotationType = (low_threshold + 180) % 360
            high_threshold_moved: RotationType = (high_threshold + 180) % 360
            shutter_moved: RotationType = (shutter + 180) % 360
            if not low_threshold_moved <= shutter_moved <= high_threshold_moved:
                if shutter > high_threshold:
                    self._sync("ccw", True)
                else:
                    self._sync("cw", True)

    def return_home(self) -> None:
        """
        Return the observatory to the home position.
        """
        self.operate("close")  # * Close shutter

        self.check_for_sync(
            int(config.get("Observatory Settings", "home_rotation")), True
        )  # * Rotate back to home position


# * Class for the socket that receives azimuthal rotation data from the control computer and calls observatory to sync with target
class Socket:
    def __init__(self) -> None:
        self.host: str = "0.0.0.0"
        self.port: int = int(config.get("Socket Settings", "port"))
        self.die_counter: multiprocessing.Value = multiprocessing.Value(
            "f", float(config.get("Socket Settings", "die_counter")) * 60
        )

        self.is_listening: multiprocessing.Value = multiprocessing.Value(
            "i", 0
        )  # * this makes the value shared across different processes
        self.can_die: multiprocessing.Value = multiprocessing.Value(
            "i", 0
        )  # * this makes the value shared across different processes
        self.data: multiprocessing.Value = multiprocessing.Value(
            "f", 0
        )  # * this makes the value shared across different processes

        self.observatory: Observatory = Observatory()

    def __read_from_socket(self) -> None:
        """
        Read data from the socket and update the observatory rotation.
        """
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind((self.host, self.port))
            s.listen(5)

            while self.is_listening.value:
                conn, addr = s.accept()
                data = conn.recv(1024)
                if not data:
                    continue
                if not self.can_die.value:
                    self.can_die.value = not self.can_die.value
                self.die_counter.value = (
                    float(config.get("Socket Settings", "die_counter")) * 60
                )

                self.data.value = float(data.decode("utf-8"))
                self.observatory.check_for_sync(self.data.value, False)

        except socket.error as e:
            logging.error(f"socket error: {e}")
            # Implement retry mechanism for socket communication
            # ...
        except Exception as e:
            logging.error(f"exception error at socket: {e}\n{traceback.format_exc()}")
        finally:
            s.close()

    def __death_count(self) -> None:
        """
        Count down the time until the observatory returns to the home position.
        """
        while self.can_die.value:
            time.sleep(1)
            if self.observatory.encoder.is_home:
                continue
            self.die_counter.value -= 1

            if self.die_counter.value >= 300:
                if self.die_counter.value % 300 == 0:
                    logging.warning(
                        f"dome automatically shutting down in {self.die_counter.value} seconds"
                    )
            elif self.die_counter.value >= 30:
                if self.die_counter.value % 30 == 0:
                    logging.warning(
                        f"dome automatically shutting down in {self.die_counter.value} seconds"
                    )
            else:
                logging.warning(
                    f"dome automatically shutting down in {self.die_counter.value} seconds"
                )

            if self.die_counter.value < 0:
                self.observatory.return_home()
                self.can_die.value = False
                self.die_counter.value = (
                    float(config.get("Socket Settings", "die_counter")) * 60
                )

    def toggle_read(self) -> None:
        """
        Toggle reading data from the socket.
        """
        self.is_listening.value = not self.is_listening.value

        if self.is_listening.value:
            process = multiprocessing.Process(target=self.__read_from_socket)
            process.start()

            logging.info("begin reading socket")

    def toggle_death(self) -> None:
        """
        Toggle the death counter for returning to the home position.
        """
        self.can_die.value = not self.can_die.value

        if self.can_die.value:
            process = multiprocessing.Process(target=self.__death_count)
            process.start()

            logging.info("begin timeout counter")


# * Main function
def main() -> None:
    """
    Main function to create and start the Socket instance.
    """
    socket = Socket()

    socket.toggle_read()
    socket.toggle_death()
    socket.observatory.encoder.toggle_measure()


if __name__ == "__main__":
    main()
    while True:
        time.sleep(1)

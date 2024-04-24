# Import required modules
import os
import socket
import time
import logging
import configparser
import tkinter as tk
from typing import Optional
from astropy.io import fits
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Read configuration settings
config = configparser.ConfigParser()
config_file_path = "./forPc/config.ini"

try:
    config.read(config_file_path)
except FileNotFoundError:
    logging.error(f"Configuration file not found: {config_file_path}")
    exit(1)
except Exception as e:
    logging.error(f"Error reading configuration file: {e}")
    exit(1)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("./forPc/mittens.log"),
        logging.StreamHandler(),
    ],
)

# Define constants
SOCKET_PI_ADDRESS = config.get("Socket Settings", "pi_address")
SOCKET_PORT = int(config.get("Socket Settings", "port"))
FOLDER_TO_WATCH = config.get("Folder Settings", "folder_path")


def send_azimuth(azimuth: Optional[float]) -> None:
    """
    Send the azimuthal value to the Raspberry Pi over a socket connection.

    Args:
        azimuth (Optional[float]): The azimuthal value to send.
    """
    try:
        # Create socket object
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        # Connect to the server
        sock.connect((SOCKET_PI_ADDRESS, SOCKET_PORT))

        # Send the message (azimuth value)
        message = str(azimuth)
        sock.send(message.encode("utf-8"))

        # Close the connection
        sock.close()

    except socket.error as e:
        logging.error(f"Azimuth socket error: {e}")
    except Exception as e:
        logging.error(f"Exception error when sending azimuth: {e}")


def send_controls(control: Optional[str]) -> None:
    """
    Send controls to the Raspberry Pi over a socket connection.

    Args:
        control (Optional[str]): The control to send.
    """
    try:
        # Create socket object
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        # Connect to the server
        sock.connect((SOCKET_PI_ADDRESS, SOCKET_PORT))

        # Send the message (control value)
        message = str(control)
        sock.send(message.encode("utf-8"))

        # Close the connection
        sock.close()

    except socket.error as e:
        logging.error(f"Control socket error: {e}")
    except Exception as e:
        logging.error(f"Exception error when sending control: {e}")


class FITSEventHandler(FileSystemEventHandler):
    """
    Event handler for monitoring the FITS image folder and sending azimuthal data.
    """

    def on_created(self, event) -> None:
        """
        Handler for the 'created' event.

        Args:
            event: The event object representing the file system event.
        """
        if event.is_directory:
            return

        # Check if the file is a FITS file
        if os.path.splitext(event.src_path)[1] == ".fits":
            time.sleep(2)  # Wait for the file to be fully written

            # Open the FITS image
            try:
                header = fits.getheader(event.src_path)
                centaz_value = header.get("CENTAZ")
                send_azimuth(centaz_value)
            except Exception as e:
                logging.error(f"Error reading FITS header: {e}")


def main() -> None:
    """
    Main function to start the file monitoring and event handling.
    """
    event_handler = FITSEventHandler()
    observer = Observer()
    observer.schedule(event_handler, FOLDER_TO_WATCH, recursive=False)
    observer.start()

    root = tk.Tk()

    root.geometry("256x128")

    root.title("Emergency Observatory Control")

    # Configure the root window's background color
    root.configure(
        bg="white",
        padx=10,
        pady=10,
    )
    root.grid()

    toggle_button = tk.Button(
        root,
        text="Toggle Shutter",
        command=lambda: send_controls("toggle"),
        bg="blue",
        fg="white",
        width=10,
        height=4,
        padx=5,
        pady=5,
        cursor="hand2",
    )
    abort_button = tk.Button(
        root,
        text="Abort",
        command=lambda: send_controls("abort"),
        bg="red",
        fg="white",
        width=10,
        height=4,
        padx=5,
        pady=5,
        cursor="hand1",
    )

    toggle_button.pack(
        side=tk.LEFT,
        padx=10,
    )
    abort_button.pack(
        side=tk.RIGHT,
        padx=10,
    )

    root.mainloop()


if __name__ == "__main__":
    main()

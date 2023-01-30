import requests
import os
import argparse
import yaml

from datetime import datetime
from time import sleep
from requests.exceptions import ConnectionError, Timeout

SLEEP_INTERVAL = 60
DELAY_FINISHED = 60 * 15

parser = argparse.ArgumentParser(description="Run Drone Monitor")
parser.add_argument(
    "-d",
    "--domain",
    action="store",
    type=str,
    help="Base domain address of Drone service",
)
parser.add_argument("-k", "--api-key", action="store", type=str, help="Api key")
parser.add_argument(
    "--no-notify",
    action="store_true",
    help="Do not send a popup message when build is done",
)


class DroneMonitor:
    FORMAT_BOLD = "\033[1m"
    FORMAT_GREEN = "\033[92m"
    FORMAT_YELLOW = "\033[93m"
    FORMAT_RED = "\033[91m"
    FORMAT_END = "\033[0m"

    def __init__(self, url, api_key, no_notify=False):
        if not (url and api_key):
            raise Exception("Base url or API key not provided.")
        self.base_url = url
        self.no_notify = no_notify
        self.session = requests.Session()
        self.session.headers = {"Authorization": f"Bearer {api_key}"}
        self.login = self.get_user_login()
        self.current_builds = []

    # DRONE API
    def get(self, url):
        response = self.session.get(self.base_url + url, timeout=10)
        if not response.ok:
            raise Exception(f"Error from Drone response: {response.json()['message']}")
        return response

    def get_user_login(self):
        url = "api/user"
        response = self.get(url)
        return response.json().get("login")

    def get_build_info(self, build_item):
        build_slug = build_item.get("slug", "")
        build_number = build_item.get("build", {}).get("number")
        if not (build_slug and build_number):
            raise Exception("Cannot request build info")
        url = f"api/repos/{build_slug}/builds/{build_number}"
        return self.get(url).json()

    def get_recent_builds(self):
        def filter_recent_builds(item):
            build = item.get("build", {})
            if build.get("author_login") == self.login:
                build_status = build.get("status")

                if build_status in ["success", "failure"]:
                    # Show finished builds from last 5 minutes
                    time_finished = datetime.fromtimestamp(build.get("finished", 1))
                    if (datetime.now() - time_finished).seconds < DELAY_FINISHED:
                        return True
                else:
                    # Pending builds
                    return True
            return False

        url = "api/user/builds"
        response = self.get(url)
        recent_builds = list(filter(filter_recent_builds, response.json()))
        for build_item in recent_builds:
            # update with build steps
            build_item["build"].update(self.get_build_info(build_item))
        return recent_builds

    # PROCESSING API INFO
    def update_current_builds(self):
        recent_builds = self.get_recent_builds()

        if not self.no_notify:
            self.check_for_status_change(recent_builds)
        self.current_builds = sorted(
            recent_builds, key=lambda item: item.get("build", {}).get("started", 0)
        )

    def check_for_status_change(self, recent_builds):
        for done_build in filter(
            lambda b: b["build"].get("status") in ["success", "failure"], recent_builds
        ):
            done_build_number = done_build["build"].get("number")
            done_build_status = done_build["build"].get("status")
            matching_build = [
                b
                for b in self.current_builds
                if b["build"].get("number") == done_build_number
            ]
            if (
                matching_build
                and matching_build[0]["build"].get("status") != done_build_status
            ):
                title = f"Drone build {done_build_status}"
                message = f"{done_build['name']} at {done_build['build'].get('source')}"
                os.system(f'notify-send "{title}" "{message}"')

    # TEXT FORMATTING
    def format_status_text(self, status, text):
        formatted_text = text
        if status == "running":
            formatted_text = self.FORMAT_YELLOW + text + self.FORMAT_END
        elif status == "success":
            formatted_text = self.FORMAT_GREEN + text + self.FORMAT_END
        elif status == "failure":
            formatted_text = self.FORMAT_RED + text + self.FORMAT_END
        return formatted_text

    # OPERATIONS ON DISPLAY ELEMENTS
    def create_progress_bar(self, build_item):
        bar_item = "████"
        progress_bar = ""

        # build_info = self.get_build_info(build_item)
        for stage in build_item["build"].get("stages", []):
            for step in stage.get("steps", []):
                progress_bar += self.format_status_text(step.get("status"), bar_item)
        return progress_bar

    def update_build_screen(self):
        self.update_current_builds()
        os.system("clear")
        for build_item in self.current_builds:
            build = build_item["build"]
            repo_name = build_item.get("name", "")
            branch_name = build.get("source")
            status = build.get("status")
            date_started = datetime.fromtimestamp(build.get("started", 0))
            date_finished = build.get("finished", 0)
            if date_finished:
                date_finished = datetime.fromtimestamp(date_finished)
                build_time = date_finished - date_started
            else:
                build_time = datetime.now() - date_started

            line = [
                self.FORMAT_BOLD + repo_name + self.FORMAT_END,
                branch_name,
                self.format_status_text(status, status),
                f"{build_time.seconds // 60}:{build_time.seconds % 60:02}",
            ]
            print(" ".join(line))
            print(self.create_progress_bar(build_item))
            print()


if __name__ == "__main__":
    args = {}
    try:
        yaml_config = yaml.safe_load(open("config.yml"))
        args = yaml_config
    except FileNotFoundError:
        pass
    args.update({k: v for k, v in vars(parser.parse_args()).items() if v})

    drone_monitor = DroneMonitor(
        args.get("domain"), args.get("api_key"), args.get("no_notify")
    )
    try:
        while True:
            try:
                drone_monitor.update_build_screen()
            except (ConnectionError, Timeout):
                os.system("clear")
                print(f"Connection error. Will retry in {SLEEP_INTERVAL}s.")
            sleep(SLEEP_INTERVAL)
    except KeyboardInterrupt:
        pass

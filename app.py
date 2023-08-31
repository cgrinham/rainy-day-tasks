from dataclasses import dataclass
import uuid
import json
import requests
import datetime
import logging
import multiprocessing
from dateutil.parser import parse
from flask import Flask, request, render_template, Response
from flask.views import MethodView

app = Flask(__name__)
LOGGER = logging.getLogger('rainy-day')
LOGGER.setLevel(logging.INFO)


RATE_PER_SECOND = 5
TASKS = None


class TaskQueue:
    def __init__(self, host, retry_limit=-1):
        self.host = host
        self.retry_limit = retry_limit


QUEUE_MAP = {}
try:
    with open('hosts.json') as hosts_file:
        data = json.load(hosts_file)
        for parent, taskqueue in data.items():
            QUEUE_MAP[parent] = TaskQueue(**taskqueue)
except ValueError:
    LOGGER.info("hosts.json file not found")


class AppEngineRequest:
    def __init__(self, http_method, relative_uri, app_engine_routing=None, headers=None, body=None):
        self.method = http_method
        self.app_engine_routing = app_engine_routing
        self.relative_uri = relative_uri
        self.headers = headers
        self.body = body

    def make_request(self, host):
        try:
            request_args = {
                "url": f"{host}{self.relative_uri}",
                "method": self.method or "GET",
            }
            if self.body:
                request_args["data"] = self.body
            if self.headers:
                request_args["headers"] = self.headers
            LOGGER.info(f"Making {self.method} request to {self.relative_uri}")
            return requests.request(**request_args), None
        except Exception as exception:
            logging.exception("There was an exception processing the request")
            return None, exception


@dataclass
class Task:
    name: str
    schedule_time: datetime.datetime
    create_time: datetime.datetime
    dispatch_deadline: datetime.datetime
    dispatch_count: int
    response_count: int
    first_attempt: dict
    last_attempt: dict
    request: AppEngineRequest
    complete_time: datetime.datetime
    parent: str
    host: str
    retry_limit: int
    uuid: str

    @staticmethod
    def get_datetime(value):
        if value:
            return parse(value)
        return None

    def __init__(self, task, parent=None):
        self.name = task.get("name")
        self.uuid = str(uuid.uuid4())
        if not self.name:
            self.name = self.uuid
        self.schedule_time = self.get_datetime(
            task.get("schedule_time")) or datetime.datetime.now()
        self.create_time = datetime.datetime.now()
        self.dispatch_deadline = self.get_datetime(task.get("dispatch_deadline"))

        # requests made/tries
        self.dispatch_count = task.get("dispatch_count", 0)
        # responses received
        self.response_count = task.get("response_count", 0)

        self.first_attempt = None
        self.last_attempt = None

        self.request = AppEngineRequest(**task.get("app_engine_http_request"))

        self.complete_time = None
        self.error = None
        self.parent = parent
        if parent:
            queue = QUEUE_MAP.get(parent)
            self.host = queue.host
            self.retry_limit = queue.retry_limit
        else:
            self.retry_limit = 3
            self.host = None

    @property
    def remaining_tries(self):
        return 0 if self.retry_limit < 0 else self.retry_limit - self.dispatch_count

    def process(self):
        LOGGER.warning(f"Triggering {self}")
        self.dispatch_count += 1
        response, exception = self.request.make_request(self.host)
        self.exception = exception
        self.response_count += 1

        if not self.first_attempt:
            self.first_attempt = response
        self.last_attempt = response
        self.complete_time = datetime.datetime.now()
        if exception or not response.ok:
            if exception:
                LOGGER.warning(f"Task failed with exception: {exception}")
            elif not response.ok:
                LOGGER.warning(f"Task failed with error: {response.status_code}")
            if self.remaining_tries > 0:
                return False
        return True

    @classmethod
    def trigger(cls, task):
        complete = False
        delay = 0.5
        while not complete:
            complete = task.process()
            if not complete:
                delay = delay * 2
        LOGGER.info("TASK COMPLETE")
        TASKS[task.name] = task


class Index(MethodView):
    def get(self):
        return render_template('index.html', tasks=TASKS)

    def post(self):
        data = request.json
        parent = request.args.get("parent")
        task = Task(data, parent=parent)
        LOGGER.info(f"Task created: {task.name}")
        TASKS[task.name] = task
        task_process = multiprocessing.Process(
                target=Task.trigger, args=(task,))
        task_process.start()
        return Response(status=201)


app.add_url_rule('/', view_func=Index.as_view('index'))


if __name__ == "__main__":
    TASKS = multiprocessing.Manager().dict()
    app.run(host="localhost", port=8500)

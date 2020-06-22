# Rainy Day Tasks
A pretty inaccurate and incomplete version of Google Cloud Tasks for local development.
If you are using App Engine HTTP requests, you must create a file called `hosts.json` to map your projects to local URLs, like:

    {
        "projects/my-project-id/locations/europe-west2/queues/my-queue-name": {
            "host": "http://localhost:8002",
            "retry_limit": 3
        }
    }


## Example
The server will accept the same payload that you would usually pass to the CloudTasksClient, like so:

    def create_task(url, queue='default', payload=None, countdown=None):
        """
        Create a task for a given queue with an arbitrary payload.
              url : relative url to tasks handler in this project
            queue : string name of the target queue
          payload : json payload
        countdown : number of seconds until the task should execute
        """
        client = tasks_v2.CloudTasksClient()

        project = settings.PROJECT_ID
        location = settings.PROJECT_LOCATION

        parent = client.queue_path(project, location, queue)
        task = {
            'app_engine_http_request': {
                'http_method': 'POST',
                'relative_uri': url
            }
        }
        if payload is not None:
            if not isinstance(payload, str):
                payload = json.dumps(payload, cls=DjangoJSONEncoder)
            converted_payload = payload.encode()
            task['app_engine_http_request']['body'] = converted_payload

        if countdown is not None:
            target_time = datetime.datetime.utcnow() + datetime.timedelta(seconds=countdown)
            timestamp = timestamp_pb2.Timestamp()
            timestamp.FromDatetime(target_time)
            task['schedule_time'] = timestamp

        if os.getenv('GAE_APPLICATION'):
            response = client.create_task(parent, task)
            logging.info('Created task %r', response.name)
        else:
            try:
                logging.info("Create task on local rainy day server")
                logging.info(task)
                task['app_engine_http_request']['body'] = payload
                response = requests.post(
                    f"http://localhost:8500/?parent={parent}",
                    json=task)
            except requests.exceptions.ConnectionError:
                logging.info("Connection error contacting rainy day server, "
                             "local server probably not running")
                response = None
            else:
                print(response.status_code)
        return response



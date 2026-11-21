FROM public.ecr.aws/lambda/python:3.12

COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN python -m pip install --no-cache-dir -r requirements.txt --target "${LAMBDA_TASK_ROOT}"

COPY src ${LAMBDA_TASK_ROOT}/src

# Events: {"source": "istdaten_v2", "operating_day": "YYYY-MM-DD"},
# {"action": "plan_istdaten_sync"}, municipality_weather batches (see infra/runtime.md)
CMD ["src.run.handler"]

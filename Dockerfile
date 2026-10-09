FROM public.ecr.aws/lambda/python:3.12

COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN python -m pip install --no-cache-dir -r requirements.txt --target "${LAMBDA_TASK_ROOT}"

COPY src ${LAMBDA_TASK_ROOT}/src

# Event: {"source": "weather"}
CMD ["src.run.handler"]

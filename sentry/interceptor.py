from dataclasses import asdict, is_dataclass
from typing import Any, Union

import sentry_sdk
from temporalio import activity, workflow
from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    Interceptor,
)


def _set_common_workflow_tags(
    info: Union[workflow.Info, activity.Info], scope: sentry_sdk.Scope
):
    scope.set_tag("temporal.workflow.type", info.workflow_type)
    scope.set_tag("temporal.workflow.id", info.workflow_id)


class _SentryActivityInboundInterceptor(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        transaction_name = input.fn.__module__ + "." + input.fn.__qualname__
        scope_ctx_manager = sentry_sdk.configure_scope()
        with scope_ctx_manager as scope, sentry_sdk.start_transaction(
            name=transaction_name
        ):
            scope.set_tag("temporal.execution_type", "activity")
            activity_info = activity.info()
            _set_common_workflow_tags(activity_info, scope)
            scope.set_tag("temporal.activity.id", activity_info.activity_id)
            scope.set_tag("temporal.activity.type", activity_info.activity_type)
            scope.set_tag("temporal.activity.task_queue", activity_info.task_queue)
            scope.set_tag(
                "temporal.workflow.namespace", activity_info.workflow_namespace
            )
            scope.set_tag("temporal.workflow.run_id", activity_info.workflow_run_id)
            try:
                return await super().execute_activity(input)
            except Exception as e:
                if len(input.args) == 1 and is_dataclass(input.args[0]):
                    scope.set_context("temporal.activity.input", asdict(input.args[0]))
                scope.set_context("temporal.activity.info", activity.info().__dict__)
                sentry_sdk.capture_exception(e)
                raise e
            finally:
                scope.clear()


class SentryInterceptor(Interceptor):
    """Temporal Interceptor class which will report workflow & activity exceptions to Sentry"""

    def intercept_activity(
        self, next: ActivityInboundInterceptor
    ) -> ActivityInboundInterceptor:
        """Implementation of
        :py:meth:`temporalio.worker.Interceptor.intercept_activity`.
        """
        return _SentryActivityInboundInterceptor(super().intercept_activity(next))

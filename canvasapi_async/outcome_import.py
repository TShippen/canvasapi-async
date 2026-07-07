from canvasapi_async.canvas_object import CanvasObject


class OutcomeImport(CanvasObject):
    def __str__(self):
        return "{} ({})".format(self.workflow_state, self.id)

from canvasapi_async.canvas_object import CanvasObject


class CommMessage(CanvasObject):
    def __str__(self):
        return "{} ({})".format(self.subject, self.id)

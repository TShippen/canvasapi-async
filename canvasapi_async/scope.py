from canvasapi_async.canvas_object import CanvasObject


class Scope(CanvasObject):
    def __str__(self):
        return "{}".format(self.resource)

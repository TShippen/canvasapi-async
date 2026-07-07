from canvasapi_async.canvas_object import CanvasObject


class JWT(CanvasObject):
    def __str__(self):
        return "{}".format(self.token)

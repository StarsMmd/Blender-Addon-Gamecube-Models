from ...Node import Node

# Scene Data
class SceneData(Node):
    class_name = "Scene Data"
    fields = [
        ('models', 'ModelSet[]'),
        ('camera', 'CameraSet'),
        ('lights', 'LightSet[]'),
        ('fog', 'Fog')
    ]

    serializes_subtree = True

    def serializationOrder(self):
        """Emission order of the scene subtree.

        The compiler lays the scene tail out in two bands: first the *leaves*
        (each light's WObject + Light struct, then the camera's WObjects +
        Camera struct), then the *containers* (ModelSets, CameraSet, LightSets),
        and finally the SceneData struct itself. Within both the light-leaf band
        and the LightSet container band the entries run in reverse LightSet-index
        order; everything else is forward."""
        def node_list(value):
            return [n for n in value if isinstance(n, Node)] if isinstance(value, list) else []

        order = []
        lights = node_list(self.lights)
        models = node_list(self.models)
        camera_set = self.camera if isinstance(self.camera, Node) else None

        # 1. Light leaves — reverse LightSet-index order, WObject then Light.
        for light_set in reversed(lights):
            light = getattr(light_set, 'light', None)
            while isinstance(light, Node):
                position = getattr(light, 'position', None)
                if isinstance(position, Node):
                    order.append(position)
                order.append(light)
                light = getattr(light, 'link', None)

        # 2. Camera leaves — position WObject, interest WObject, then Camera.
        if camera_set is not None:
            camera = getattr(camera_set, 'camera', None)
            if isinstance(camera, Node):
                for field in ('position', 'interest'):
                    wobject = getattr(camera, field, None)
                    if isinstance(wobject, Node):
                        order.append(wobject)
                order.append(camera)

        # 3. Container band: ModelSets (forward), CameraSet, then LightSets
        #    in reverse index order.
        order.extend(models)
        if camera_set is not None:
            order.append(camera_set)
        order.extend(reversed(lights))

        # 4. Fog, then the SceneData struct itself.
        fog = getattr(self, 'fog', None)
        if isinstance(fog, Node):
            order.append(fog)
        order.append(self)
        return order

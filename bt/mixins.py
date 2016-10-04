# -*- coding: utf-8 -*-


class ReprMixin:

    """Provides friendly `__repr__` method for all models to print
       fields mentioned in `__repr_fields__`. Output format is:
       <ModelName(field1=value,.., fieldN=value)>
    """

    def __repr__(self):
        model_name = self.__class__.__name__
        fields = getattr(self, '__repr_fields__', [])
        if fields:
            message = ', '.join("{}={}".format(
                field, getattr(self, field, None))
                            for field in fields)
            return "<{}({})>".format(model_name, message)
        else:
            return super().__repr__()

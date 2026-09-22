from rest_framework.exceptions import APIException


class PharmacyError(APIException):
    status_code = 400
    default_detail = 'Pharmacy domain error'
    default_code = 'pharmacy_error'

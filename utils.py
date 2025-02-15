class RequestError(Exception):
    
    def __init__(self, message: str, url: str = "", status_code: int = 0):
        super().__init__(message)
        self.url = url
        self.status_code = status_code

    def __str__(self):
        return f"{self.args[0]} (URL: {self.url}, Status: {self.status_code})"
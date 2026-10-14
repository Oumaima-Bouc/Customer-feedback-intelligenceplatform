class ConsulKeys:
    @staticmethod
    def service_config(service_name: str) -> str:
        return f"config/{service_name}"
    @staticmethod
    def restart_required(service_name: str) -> str:
        return f"config/restart-required/{service_name}"

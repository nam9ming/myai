package kr.ac.myai.backend.local;

import org.springframework.context.annotation.Profile;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;

@RestController
@Profile("local-api")
@RequestMapping(value = "/local", produces = MediaType.APPLICATION_JSON_VALUE)
public class LocalManagementController {
    private final LocalManagementService management;

    public LocalManagementController(LocalManagementService management) { this.management = management; }

    @PostMapping(value = "/documents", consumes = MediaType.APPLICATION_JSON_VALUE)
    public LocalManagementService.Result documents(@RequestBody byte[] body) { return management.documents(body); }

    @PostMapping(value = "/extractions/import", consumes = MediaType.APPLICATION_JSON_VALUE)
    public LocalManagementService.Result extraction(@RequestBody byte[] body) { return management.extraction(body); }

    @PutMapping(value = "/events/{eventId}/review", consumes = MediaType.APPLICATION_JSON_VALUE)
    public LocalManagementService.Result review(@PathVariable String eventId, @RequestBody byte[] body) {
        return management.review(eventId, body);
    }

    @PostMapping(value = "/reviews/import", consumes = MediaType.APPLICATION_JSON_VALUE)
    public LocalManagementService.Result reviews(@RequestBody byte[] body) { return management.reviews(body); }

    @PostMapping(value = "/publish", consumes = MediaType.APPLICATION_JSON_VALUE)
    public LocalManagementService.Result publish(@RequestBody byte[] body) { return management.publish(body); }
}
